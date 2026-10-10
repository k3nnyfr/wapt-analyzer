"""Re-sign store packages with the user's key, using WAPT's own libraries.

This script is NOT imported by wapt-analyzer: it is executed by ``waptpython`` (the Python
interpreter shipped with the WAPT agent, Windows or Linux/macOS) so that package signing is done by
the reference implementation (``waptpackage.PackageEntry.sign_package``), as ``wapt-signpackages``
does.

Protocol: a JSON job on stdin, one JSON object per processed package on stdout.

    {
      "certificate": "/path/to/signer.crt",
      "private_key": "/path/to/signer.pem",
      "password": "...",                       # private key passphrase ("" if not encrypted)
      "trusted_certs": ["/path/to/tis.crt"],   # certificates trusted to verify the store packages
      "prefix": "tsi",
      "maturity": null,                        # optional new maturity
      "verify": "full",                        # "full" (files + control), "control" or "none"
      "jobs": [{"source": "/path/a.wapt", "output_dir": "/path/out"}]
    }

A job with ``control`` instead of a source file builds a host or group package from its control attributes
(``build_management_package``, as the WAPT console does), its version incremented (``inc_build``) unless
``inc`` is false:

    {"source": "<host uuid>", "section": "host", "inc": true,
     "control": {"package": "<uuid>", "version": "5", "depends": "..."}, "output_dir": "/path/out"}
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

from waptcrypto import SSLCABundle, SSLPrivateKey
from waptpackage import PackageEntry
from waptutils import is_pem_key_encrypted


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def process(job, spec, key, signer_chain, trusted, signers):
    source = job["source"]
    output_dir = job["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    emit({"event": "start", "source": source})
    work_dir = tempfile.mkdtemp(prefix="wapt-analyzer-", dir=output_dir)
    try:
        work_file = os.path.join(work_dir, os.path.basename(source))
        shutil.copyfile(source, work_file)

        pe = PackageEntry(waptfile=work_file)
        original = pe.asrequirement()
        # 1. Authenticity of the source package
        verify = spec.get("verify", "full")
        verified_by = None
        if verify != "none":
            emit({"event": "stage", "source": source, "stage": "verify"})
        if verify == "full":
            unzip_dir = os.path.join(work_dir, "unzipped")
            pe.unzip_package(target_dir=unzip_dir, cabundle=trusted)  # raises if files or signature are bad
            shutil.rmtree(unzip_dir, ignore_errors=True)
            pe = PackageEntry(waptfile=work_file)
        if verify != "none":
            verified_by = pe.check_control_signature(trusted_bundle=trusted)

        # 2. Rename to the user's prefix (package and its dependencies)
        pe.change_prefix(spec["prefix"])
        pe.change_depends_conflicts_prefix(spec["prefix"])
        if spec.get("maturity"):
            pe.maturity = spec["maturity"]

        # 3. Sign in place, as wapt-signpackages does
        emit({"event": "stage", "source": source, "stage": "sign"})
        pe.sign_package(private_key=key, certificate=signer_chain)
        final_name = pe.make_package_filename()
        final_path = os.path.join(output_dir, final_name)
        if os.path.exists(final_path):
            os.remove(final_path)
        shutil.move(pe.localpath, final_path)

        # 4. Check the result with the signer certificate only
        check = PackageEntry(waptfile=final_path)
        check.check_control_signature(trusted_bundle=signers)
        emit({
            "source": source, "ok": True, "original": original,
            "package": check.package, "version": check.version, "maturity": check.maturity,
            "depends": check.depends, "conflicts": check.conflicts,
            "filename": final_name, "path": final_path, "size": os.path.getsize(final_path),
            "verified_by": getattr(verified_by, "cn", None) if verified_by else None,
            "signer": check.signer,
        })
    except Exception as e:  # report and continue with the next package
        emit({"source": source, "ok": False, "error": f"{type(e).__name__}: {e}",
              "trace": traceback.format_exc()})
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def process_host(job, key, signer_chain, signers):
    source = job["source"]
    emit({"event": "start", "source": source})
    try:
        control = dict(job["control"])
        os.makedirs(job["output_dir"], exist_ok=True)
        pe = PackageEntry(package=control.pop("package"), version=control.pop("version") or "0",
                          section=job.get("section") or "host", **control)
        if job.get("inc", True):
            pe.inc_build()
        emit({"event": "stage", "source": source, "stage": "sign"})
        path = pe.build_management_package(target_directory=job["output_dir"])
        pe.sign_package(private_key=key, certificate=signer_chain)
        check = PackageEntry(waptfile=path)
        check.check_control_signature(trusted_bundle=signers)
        emit({"source": source, "ok": True, "package": check.package, "version": check.version,
              "depends": check.depends, "filename": os.path.basename(path), "path": path,
              "size": os.path.getsize(path), "signer": check.signer})
    except Exception as e:
        emit({"source": source, "ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})


def main():
    spec = json.load(sys.stdin)
    # The key is decrypted once here and reused for every package of the job
    password = spec.get("password") or None
    if password is None and is_pem_key_encrypted(spec["private_key"]):
        # waptcrypto would prompt on the console of this process, which has none: it would hang
        raise SystemExit(f"The private key {spec['private_key']} is encrypted: a passphrase is required")
    # None for an unencrypted key: waptcrypto rejects a password, even empty, for such a key
    key = SSLPrivateKey(spec["private_key"], password=password)
    signers = SSLCABundle()
    signers.add_certificates_from_pem(pem_filename=spec["certificate"], trusted=True)
    signer_chain = signers.certificates()
    if not signer_chain:
        raise SystemExit(f"No certificate in {spec['certificate']}")
    if not signer_chain[0].match_key(key):
        raise SystemExit(f"The private key does not match certificate {signer_chain[0].cn}")
    if not signer_chain[0].is_code_signing:
        sys.stderr.write(f"WARNING: {signer_chain[0].cn} is not a code signing certificate, "
                         "packages with setup.py will fail\n")

    trusted = SSLCABundle()
    for path in spec.get("trusted_certs") or []:
        trusted.add_certificates_from_pem(pem_filename=path, trusted=True)

    for job in spec["jobs"]:
        if job.get("control") is not None:
            process_host(job, key, signer_chain, signers)
        else:
            process(job, spec, key, signer_chain, trusted, signers)


if __name__ == "__main__":
    main()
