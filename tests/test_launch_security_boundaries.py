"""Release-risk controls; runnable with unittest without the full agent environment."""

import ast
import json
from pathlib import Path
import subprocess
import time
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
DECODE_SITES = {
    ("plugins/dashboard_auth/_shared.py", "verify_jwt"): 2,
    ("plugins/cron_providers/chronos/verify.py", "verify_nas_fire_token"): 1,
    ("tools/skills_sync_client.py", "resolve_identity"): 1,
}


class ReleaseBoundaryTests(unittest.TestCase):
    def test_jwt_decode_inventory_and_fresh_options(self):
        """New/aliased JWT entry points require an explicit security review."""
        sites = {}
        paths = subprocess.check_output(
            ["git", "ls-files", "-z", "*.py"], cwd=ROOT
        ).decode().split("\0")
        for path in filter(None, paths):
            if path.startswith("tests/"):
                continue
            source = (ROOT / path).read_text(encoding="utf-8")
            if "jwt" not in source:
                continue
            tree = ast.parse(source, filename=path)
            modules, imported_decoders, constructors = set(), set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(a.asname or a.name.split(".")[0] for a in node.names
                                   if a.name in ("jwt", "jwt.api_jwt"))
                elif isinstance(node, ast.ImportFrom) and node.module in ("jwt", "jwt.api_jwt"):
                    imported_decoders.update(
                        a.asname or a.name for a in node.names
                        if a.name in ("decode", "decode_complete")
                    )
                    constructors.update(a.asname or a.name for a in node.names
                                        if a.name == "PyJWT")
            # Stateful PyJWT wrappers require a new review instead of bypassing the inventory.
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertFalse(
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id in modules and node.func.attr == "PyJWT",
                        (path, node.lineno),
                    )
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, constructors,
                                     (path, node.lineno))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(func):
                    if not isinstance(call, ast.Call):
                        continue
                    target = call.func
                    is_decode = (
                        isinstance(target, ast.Attribute)
                        and target.attr in ("decode", "decode_complete")
                        and isinstance(target.value, ast.Name)
                        and target.value.id in modules
                    ) or (isinstance(target, ast.Name) and target.id in imported_decoders)
                    if not is_decode:
                        continue
                    key = (path, func.name)
                    sites[key] = sites.get(key, 0) + 1
                    options = next((k.value for k in call.keywords if k.arg == "options"), None)
                    if options is not None:
                        self.assertIsInstance(options, ast.Dict, (path, call.lineno))
                    else:
                        # Chronos constructs both the kwargs and nested options in this invocation.
                        self.assertEqual(key, ("plugins/cron_providers/chronos/verify.py",
                                               "verify_nas_fire_token"))
                        assignment = next(n for n in ast.walk(func)
                                          if isinstance(n, ast.AnnAssign)
                                          and isinstance(n.target, ast.Name)
                                          and n.target.id == "decode_kwargs")
                        self.assertIsInstance(assignment.value, ast.Call)
                        self.assertEqual(assignment.value.func.id, "dict")
                        self.assertIsInstance(next(k.value for k in assignment.value.keywords
                                                   if k.arg == "options"), ast.Dict)
                        self.assertTrue(any(k.arg is None and isinstance(k.value, ast.Name)
                                            and k.value.id == "decode_kwargs" for k in call.keywords))
        self.assertEqual(sites, DECODE_SITES)

    def test_braces_is_only_in_website_lock(self):
        for name in ("package-lock.json", "website/package-lock.json",
                     "plugins/platforms/photon/sidecar/package-lock.json",
                     "scripts/whatsapp-bridge/package-lock.json"):
            lock = json.loads((ROOT / name).read_text())
            copies = [v for p, v in lock["packages"].items()
                      if p.endswith("node_modules/braces")]
            if name.startswith("website/"):
                self.assertTrue(copies)
            else:
                self.assertEqual(copies, [], name)

    def test_site_publication_does_not_run_build_tools(self):
        # Keep the YAML dependency confined to the workflow-specific check.
        import yaml

        workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-site.yml").read_text())
        build = workflow["jobs"]["build-docs"]
        self.assertEqual(build["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(workflow["permissions"], {"contents": "read", "actions": "read"})
        self.assertNotIn("environment", build)
        self.assertNotIn("secrets.", json.dumps(build))
        checkout = build["steps"][0]
        self.assertIs(checkout["with"]["persist-credentials"], False)
        deploy = workflow["jobs"]["deploy-docs"]
        self.assertEqual(deploy["needs"], "build-docs")
        self.assertEqual(deploy["permissions"], {"pages": "write", "id-token": "write"})
        self.assertEqual(len(deploy["steps"]), 1)
        self.assertTrue(deploy["steps"][0]["uses"].startswith("actions/deploy-pages@"))


class PyJWTArtifactTests(unittest.TestCase):
    def test_locked_distribution_preserves_options_and_rejects_bad_claims(self):
        import jwt

        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        version = next(p["version"] for p in lock["package"] if p["name"] == "pyjwt")
        self.assertEqual(jwt.__version__, version)
        secret = "release-regression-only-not-a-credential" * 2
        now = int(time.time())
        base = {"exp": now + 3600, "nbf": now - 60, "iat": now - 60,
                "aud": "marcel", "iss": "issuer", "sub": "subject", "jti": "id"}
        failures = [
            ({"exp": now - 3600}, jwt.ExpiredSignatureError),
            ({"nbf": now + 3600}, jwt.ImmatureSignatureError),
            ({"iat": now + 3600}, jwt.ImmatureSignatureError),
            ({"aud": "wrong"}, jwt.InvalidAudienceError),
            ({"iss": "wrong"}, jwt.InvalidIssuerError),
            ({"sub": 123}, jwt.exceptions.InvalidSubjectError),
            ({"jti": 123}, jwt.exceptions.InvalidJTIError),
        ]
        for decode in (jwt.decode, jwt.decode_complete):
            for changes, error in failures:
                with self.subTest(decoder=decode.__name__, changes=changes):
                    options = {"verify_signature": False}
                    token = jwt.encode({**base, **changes}, secret, algorithm="HS256")
                    decode(token, options=options)
                    self.assertEqual(options, {"verify_signature": False})
                    options["verify_signature"] = True
                    with self.assertRaises(error):
                        decode(token, secret, algorithms=["HS256"], audience="marcel",
                               issuer="issuer", options=options)
                    self.assertEqual(options, {"verify_signature": True})


if __name__ == "__main__":
    unittest.main()
