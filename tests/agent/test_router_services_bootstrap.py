"""Exercise normal plugin discovery and tool dispatch, not just provider classes."""
import os
from pathlib import Path
import subprocess
import sys


def test_router_services_are_discovered_and_dispatched_without_direct_keys(tmp_path):
    script = r'''
import base64, json
from pathlib import Path
from unittest.mock import patch
import requests, yaml
import os
home=Path(os.environ["MARCEL_HOME"])
config={
    "marcel":{"router":{"mode":"marcel_router","base_url":"https://router.example/api/v1","key_env":"BOOTSTRAP_ROUTER_KEY"}},
    "image_gen":{"provider":"marcel","model":"vendor/image"},
    "video_gen":{"provider":"marcel","model":"vendor/video"},
    "web":{"search_backend":"marcel-brave","backend":"marcel-brave"},
}
(home/"config.yaml").write_text(yaml.safe_dump(config))
def reply(data=None,content=None):
    r=requests.Response();r.status_code=200
    r._content=content if content is not None else json.dumps(data).encode()
    return r
def request(method,url,**kwargs):
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"]=="Bearer test-key"
    assert url.startswith("https://router.example/api/v1/")
    if url.endswith("/images/generations"):
        return reply({"data":[{"b64_json":base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()}]})
    if url.endswith("/videos") and method=="POST": return reply({"id":"video-job"})
    if url.endswith("/videos/video-job"): return reply({"status":"completed"})
    if url.endswith("/content"): return reply(content=b"\0\0\0\x18ftypisomfixture")
    if url.endswith("/tools/search"): return reply({"data":{"web":{"results":[{"url":"https://example.org","title":"Fixture"}]}}})
    raise AssertionError("Unexpected service endpoint")
video={"id":"vendor/video","metadata":{"capabilities":["video-generation"],"durations":[8],"resolutions":["720p"],"aspect_ratios":["16:9"]}}
with patch("requests.request",side_effect=request),patch("requests.get",return_value=reply({"video_models":[video]})):
    from marcel_cli.plugins import _ensure_plugins_discovered
    _ensure_plugins_discovered()
    from agent.image_gen_registry import get_active_provider as image_provider
    from agent.video_gen_registry import get_active_provider as video_provider
    assert image_provider().name=="marcel"
    assert video_provider().name=="marcel"
    from tools.image_generation_tool import _handle_image_generate
    image=json.loads(_handle_image_generate({"prompt":"fixture","aspect_ratio":"square"}))
    assert image["success"],image
    assert Path(image["image"]).is_file()
    from tools.video_generation_tool import _handle_video_generate,_build_dynamic_video_schema
    assert "job_id" in _build_dynamic_video_schema()["parameters"]["properties"]
    video=json.loads(_handle_video_generate({"prompt":"fixture","duration":8,"resolution":"720p","aspect_ratio":"16:9"}))
    assert video["success"],video
    assert Path(video["video"]).is_file()
    from agent.web_search_registry import _resolve,_configured_backend
    search=_resolve(_configured_backend("search"),capability="search")
    assert search.name=="marcel-brave"
    assert search.search("fixture",1)["success"]
'''
    env = dict(os.environ, MARCEL_HOME=str(tmp_path), BOOTSTRAP_ROUTER_KEY="test-key")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-3500:]
