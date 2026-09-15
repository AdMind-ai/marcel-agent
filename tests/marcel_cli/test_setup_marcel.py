"""Focused contract tests for Marcel's YAML-safe setup builders."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from marcel_cli import setup as setup_cli_module
from marcel_cli.default_soul import DEFAULT_SOUL_MD
from agent.onboarding import pending_google_workspace_directive
from marcel_cli.setup_marcel import (
    MARCEL_SOUL_MD,
    build_marcel_soul,
    ACTIVITY_MODEL_CHOICES,
    ACTIVITY_CAPABILITY_DEFAULTS,
    MODEL_CHOICES,
    _choose_model,
    _choose_available_models,
    _choose_direct_provider,
    _choose_capabilities,
    _choose_concurrency,
    _choose_memory_interval,
    _fallback_catalog,
    _generation_catalog,
    _vision_catalog,
    _worker_llm_catalog,
    _normalize_router_models,
    _catalog_for_activity,
    _confirm_fallback_order,
    _connect_required_direct_providers,
    _direct_provider_for_model,
    _required_direct_providers,
    build_marcel_config,
    apply_marcel_config,
    ensure_marcel_soul,
    normalize_account,
    normalize_agent_name,
    _prompt_agent_name,
    _validate_custom_endpoint_url,
    _validate_router_url,
    _mode_connection_defaults,
    _normalized_router_origin,
    _provider_for_selected_model,
    normalize_secret_reference,
    setup_marcel,
)
from marcel_cli.fallback_config import get_fallback_chain


class _SetupStub:
  def __init__(self, choice, custom=""):
    self.choice = choice
    self.custom = custom
    self.seen_choices = []
    self.seen_checklist = []
    self.pre_selected = []

  def prompt_choice(self, _label, choices, _default, **_kwargs):
    self.seen_choices = choices
    return self.choice

  def prompt(self, _label, _default=""):
    return self.custom

  def prompt_checklist(self, _label, _items, pre_selected=None):
    self.seen_checklist = list(_items)
    self.pre_selected = list(pre_selected or [])
    return list(pre_selected or [])


class MarcelSetupTests(unittest.TestCase):
  def test_marcel_defaults_are_silent_steering_with_full_access(self):
    config = apply_marcel_config({}, {
        "agent_name": "TestAgent",
        "router_mode": "direct_provider",
        "direct_provider": "xai",
        "orchestrator_model": "xai/grok-4.3",
        "orchestrator_fallback_models": [],
        "workers": [],
    })

    self.assertEqual(config["display"]["busy_input_mode"], "steer")
    self.assertFalse(config["display"]["busy_steer_ack_enabled"])
    self.assertFalse(config["display"]["platforms"]["telegram"]["long_running_notifications"])
    self.assertEqual(config["approvals"]["mode"], "off")
    self.assertEqual(config["approvals"]["unattended_mode"], "approve")

  def test_existing_fallback_key_is_shown_and_can_be_kept(self):
    prompts = []

    class ExistingKeySetup:
      @staticmethod
      def get_env_value(name):
        return "configured" if name == "OPENAI_API_KEY" else None

      @staticmethod
      def print_success(_message):
        return None

      @staticmethod
      def print_error(_message):
        return None

      @staticmethod
      def _info(*_messages):
        return None

      @staticmethod
      def prompt(label, password=False):
        prompts.append((label, password))
        return ""

      @staticmethod
      def save_env_value(_name, _value):
        raise AssertionError("Existing key should be kept when the prompt is left blank")

    _connect_required_direct_providers(
        ExistingKeySetup(),
        {
            "orchestrator_model": "anthropic/claude-sonnet-5",
            "orchestrator_fallback_models": ["openai/gpt-5.6-terra"],
            "workers": [],
        },
        skip={"anthropic"},
    )

    self.assertEqual(
        prompts,
        [("OpenAI API key (leave blank to keep the existing key)", True)],
    )

  def test_first_contact_detects_pending_google_workspace_authorization(self):
    note = pending_google_workspace_directive({
        "accounts": {
            "profiles": [{
                "kind": "google_workspace",
                "enabled": False,
                "authorization_status": "pending",
            }]
        }
    })
    self.assertIn("authorization is still pending", note)
    self.assertIn("offer to help", note)
    self.assertEqual(pending_google_workspace_directive({
        "accounts": {
            "profiles": [{
                "kind": "google_workspace",
                "enabled": True,
                "authorization_status": "verified",
            }]
        }
    }), "")

  def test_google_workspace_authorization_status_survives_normalization(self):
    pending = normalize_account({
        "type": "google_workspace",
        "name": "Google Workspace",
        "enabled": False,
        "authorization_status": "pending",
        "services": ["gmail", "calendar"],
    })
    self.assertFalse(pending["enabled"])
    self.assertEqual(pending["authorization_status"], "pending")

    verified = normalize_account({
        **pending,
        "enabled": True,
        "authorization_status": "verified",
    })
    self.assertTrue(verified["enabled"])
    self.assertEqual(verified["authorization_status"], "verified")

  def test_wizard_prompts_for_main_and_fallback_provider_keys_consecutively(self):
    saved_env = []

    def choose(label, choices, _default=0, **_kwargs):
      if label == "Connection":
        return 1
      if label == "API provider":
        return 0
      if label == "Orchestrator model":
        return next(i for i, choice in enumerate(choices) if "Claude Sonnet 5" in choice)
      raise AssertionError(f"Unexpected choice prompt: {label}")

    def checklist(label, choices, pre_selected=None):
      if label == "Choose fallback models (used in this order)":
        return [next(i for i, choice in enumerate(choices) if "GPT-5.6 Terra" in choice)]
      if label == "Choose all models Marcel may use for future orchestration":
        return list(pre_selected or [])
      raise AssertionError(f"Unexpected checklist prompt: {label}")

    def text_prompt(label, default=None, password=False):
      if label == "Agent name":
        return "TestAgent"
      if label == "Anthropic API key":
        return "anthropic-test-value"
      if label == "OpenAI API key":
        return "openai-test-value"
      raise AssertionError(f"Unexpected text prompt: {label}")

    def yes_no(label, default=True):
      return False

    with (
        patch.object(setup_cli_module, "prompt_choice", side_effect=choose),
        patch.object(setup_cli_module, "prompt_checklist", side_effect=checklist),
        patch.object(setup_cli_module, "prompt", side_effect=text_prompt),
        patch.object(setup_cli_module, "prompt_yes_no", side_effect=yes_no),
        patch.object(setup_cli_module, "get_env_value", return_value=None),
        patch.object(
            setup_cli_module, "save_env_value",
            side_effect=lambda name, value: saved_env.append((name, value))),
        patch.object(setup_cli_module, "save_config"),
        patch.object(setup_cli_module, "print_header"),
        patch.object(setup_cli_module, "print_success"),
        patch.object(setup_cli_module, "print_error"),
        patch.object(setup_cli_module, "_info"),
        patch("marcel_cli.setup_tts._setup_tts_provider"),
        patch("marcel_cli.setup_marcel._choose_voice_model"),
        patch("marcel_cli.setup_marcel._choose_image_provider"),
        patch("marcel_cli.setup_marcel.ensure_marcel_soul"),
        patch("marcel_cli.setup_marcel.ensure_memory_maintenance_job"),
    ):
      setup_marcel({})

    self.assertEqual(
        saved_env,
        [
            ("ANTHROPIC_API_KEY", "anthropic-test-value"),
            ("OPENAI_API_KEY", "openai-test-value"),
        ],
    )

  def test_bare_legacy_entrypoint_cannot_fall_back_to_legacy_setup_menu(self):
    args = SimpleNamespace(
        reset=False,
        reconfigure=False,
        quick=False,
        non_interactive=False,
        portal=False,
        section=None,
    )
    with (
        patch("marcel_cli.config.is_managed", return_value=False),
        patch.object(setup_cli_module, "ensure_marcel_home"),
        patch.object(setup_cli_module, "is_interactive_stdin", return_value=True),
        patch.object(setup_cli_module, "load_config", return_value={}),
        patch.object(setup_cli_module, "get_marcel_home", return_value=Path("/tmp/marcel-test")),
        patch.object(setup_cli_module, "get_config_path", return_value=Path("/tmp/marcel-test/config.yaml")),
        patch.object(setup_cli_module, "_backup_config_file", return_value=None),
        patch.object(setup_cli_module, "_print_banner") as print_banner,
        patch.object(setup_cli_module, "_run_setup_steps") as run_steps,
        patch.object(setup_cli_module, "prompt_choice", side_effect=AssertionError("legacy menu opened")),
        patch("sys.argv", ["marcel", "setup"]),
    ):
      setup_cli_module._run_setup_wizard_impl(args)

    self.assertIn("Marcel Setup Wizard", print_banner.call_args.args[0])
    self.assertEqual(run_steps.call_args.args[0][0][0], "Marcel Agent")

  def test_apply_marcel_config_keeps_credentials_as_environment_references(self):
    config = apply_marcel_config({}, {
        "agent_name": "Ops Marcel",
        "router_mode": "custom_endpoint",
        "base_url": "https://models.example.test/v1/",
        "api_key_ref": "MARCEL_API_KEY",
        "orchestrator_model": "orchestrator-v1",
        "workers": [{
            "name": "research",
            "activity": "search",
            "model": "search-v1",
            "recommended": True,
            "toolsets": "web, documents",
            "concurrency": "2",
            "budget": "400",
            "fallbacks": "search-small, search-backup",
        }],
        "memory_maintenance_enabled": True,
        "accounts": [{
            "type": "google_workspace",
            "name": "company",
            "services": "gmail, calendar",
            "client_secret_ref": "GOOGLE_CLIENT_SECRET",
            "refresh_token_ref": "${GOOGLE_REFRESH_TOKEN}",
        }, {
            "type": "imap_smtp",
            "host": "mail.example.test",
            "username": "agent@example.test",
            "password_ref": "IMAP_PASSWORD",
        }],
    })

    assert config["marcel"]["router"] == {
        "mode": "custom_endpoint", "base_url": "https://models.example.test/v1", "key_env": "MARCEL_API_KEY",
        "api_mode": "chat_completions",
        "catalog_path": "/v1/models",
        "health_path": "/health",
    }
    assert config["providers"]["marcel-custom"]["key_env"] == "MARCEL_API_KEY"
    assert config["delegation"]["workers"]["research"]["toolsets"] == ["web", "documents"]
    assert config["delegation"]["workers"]["research"]["max_concurrency"] == 2
    assert config["memory"]["maintenance"]["interval_hours"] == 6
    assert config["accounts"]["profiles"][0]["auth"]["client_secret_ref"] == "${GOOGLE_CLIENT_SECRET}"
    assert config["accounts"]["profiles"][1]["imap"]["password_ref"] == "${IMAP_PASSWORD}"
    assert "sk-live-this-is-a-secret" not in str(config)
    assert config["accounts"]["profiles"][1]["imap"]["password_ref"].startswith("${")
    self.assertEqual(config["display"]["platforms"]["telegram"]["tool_progress"], "off")
    self.assertFalse(config["display"]["platforms"]["telegram"]["interim_assistant_messages"])
    self.assertFalse(config["display"]["platforms"]["telegram"]["long_running_notifications"])


  def test_secret_reference_rejects_literal_secret(self):
    with self.assertRaises(ValueError):
        normalize_secret_reference("sk-live-this-is-a-secret")


  def test_google_account_keeps_all_oauth_values_as_references(self):
    account = normalize_account({
        "type": "google_workspace",
        "name": "Workspace",
        "services": ["gmail"],
        "client_id_ref": "GOOGLE_WORKSPACE_CLIENT_ID",
        "client_secret_ref": "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "refresh_token_ref": "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "access_token_ref": "GOOGLE_WORKSPACE_ACCESS_TOKEN",
        "token_expiry_ref": "GOOGLE_WORKSPACE_TOKEN_EXPIRY",
        "scopes_ref": "GOOGLE_WORKSPACE_SCOPES",
    })
    self.assertEqual(account["auth"]["mode"], "oauth")
    self.assertTrue(all(
        value.startswith("${") and value.endswith("}")
        for key, value in account["auth"].items()
        if key.endswith("_ref")
    ))
  def test_direct_provider_uses_native_runtime_provider_without_custom_url(self):
    config = apply_marcel_config({}, {
        "agent_name": "TestAgent",
        "router_mode": "direct_provider",
        "direct_provider": "anthropic",
        "api_key_ref": "ANTHROPIC_API_KEY",
        "api_mode": "anthropic_messages",
        "base_url": "https://api.anthropic.com",
        "orchestrator_model": "anthropic/claude-sonnet-5",
        "workers": [],
        "accounts": [],
    })
    self.assertEqual(config["model"], {"provider": "anthropic", "default": "claude-sonnet-5"})
    self.assertEqual(config["marcel"]["router"]["key_env"], "ANTHROPIC_API_KEY")
    self.assertNotIn("anthropic", config.get("providers", {}))


  def test_direct_provider_is_inferred_from_selected_model(self):
    self.assertEqual(_direct_provider_for_model("anthropic/claude-sonnet-5"), "anthropic")
    self.assertEqual(_direct_provider_for_model("openai/gpt-6-astra"), "openai-api")
    self.assertEqual(_direct_provider_for_model("google/gemini-3.6-flash"), "gemini")
    self.assertEqual(_direct_provider_for_model("xai/grok-4.6"), "xai")
    self.assertEqual(_direct_provider_for_model("custom/model"), "")


  def test_model_picker_exposes_recommended_and_provider_groups(self):
    setup = _SetupStub(1)
    selected = _choose_model(setup, "Orchestrator model")
    self.assertEqual(selected, MODEL_CHOICES[1][1])
    self.assertIn("Recommended", setup.seen_choices[0])
    self.assertTrue(any("Anthropic" in choice for choice in setup.seen_choices))
    self.assertTrue(any("OpenAI" in choice for choice in setup.seen_choices))
    self.assertTrue(any("Google" in choice for choice in setup.seen_choices))
    self.assertTrue(any("xAI" in choice for choice in setup.seen_choices))
    self.assertTrue(any("GPT-5.6 Terra" in choice for choice in setup.seen_choices))


  def test_model_picker_accepts_a_custom_provider_model_id(self):
    setup = _SetupStub(len(MODEL_CHOICES), "local/my-model")
    self.assertEqual(_choose_model(setup, "Worker model"), "local/my-model")


  def test_sub_agent_model_picker_is_filtered_by_activity(self):
    setup = _SetupStub(1)
    selected = _choose_model(
        setup, "Sub-agent model for image", allow_automatic=True, activity="image")
    self.assertIn(selected, [model_id for _, model_id in _worker_llm_catalog()])
    self.assertTrue(any("chat/tool" in choice.lower() for choice in setup.seen_choices))
    self.assertFalse(any("vision/reasoning" in choice.lower() for choice in setup.seen_choices))
    self.assertFalse(any("Claude Opus 5" in choice for choice in setup.seen_choices))


  def test_capability_picker_uses_activity_defaults(self):
    setup = _SetupStub(0)
    selected = set(_choose_capabilities(setup, "image"))
    self.assertEqual(selected, ACTIVITY_CAPABILITY_DEFAULTS["image"])


  def test_concurrency_picker_returns_a_bounded_choice(self):
    setup = _SetupStub(2)
    self.assertEqual(_choose_concurrency(setup, "general"), "2")


  def test_text_fallback_catalog_is_long_and_deduplicated(self):
    catalog = _fallback_catalog("general")
    model_ids = [model_id for _, model_id in catalog]
    self.assertGreaterEqual(len(model_ids), 12)
    self.assertEqual(len(model_ids), len(set(model_ids)))
    self.assertIn("openai/gpt-5.6-terra", model_ids)


  def test_fallback_provider_keys_include_secondary_gemini(self):
    providers = _required_direct_providers({
        "orchestrator_model": "openai/gpt-5.6-terra",
        "orchestrator_fallback_models": ["google/gemini-3.7-flash"],
        "workers": [{
            "model": "anthropic/claude-sonnet-5",
            "fallbacks": ["xai/grok-4.6"],
        }],
    })
    self.assertEqual(providers, ["openai-api", "gemini", "anthropic", "xai"])


  def test_direct_provider_writes_cross_provider_fallback_chain(self):
    config = apply_marcel_config({}, {
        "agent_name": "TestAgent",
        "router_mode": "direct_provider",
        "direct_provider": "openai-api",
        "api_key_ref": "OPENAI_API_KEY",
        "api_mode": "chat_completions",
        "orchestrator_model": "openai/gpt-5.6-terra",
        "orchestrator_fallback_models": ["google/gemini-3.7-flash"],
        "workers": [],
        "accounts": [],
    })
    self.assertEqual(config["model"], {
        "provider": "openai-api", "default": "gpt-5.6-terra"})
    self.assertEqual(config["fallback_providers"], [{
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_mode": "gemini",
    }])
    self.assertNotIn("fallback_model", config)


  def test_media_fallbacks_stay_capability_specific(self):
    image_ids = [model_id for _, model_id in _fallback_catalog("image")]
    video_ids = [model_id for _, model_id in _fallback_catalog("video")]
    self.assertTrue(image_ids)
    self.assertFalse(any(model_id.startswith("fal/") for model_id in image_ids))
    self.assertTrue(any("video" in model_id for model_id in video_ids))
    self.assertNotIn("anthropic/claude-opus-5", image_ids)
    self.assertNotIn("openai/gpt-5.6-luna", video_ids)


  def test_memory_interval_is_selected_from_safe_options(self):
    setup = _SetupStub(4)
    self.assertEqual(_choose_memory_interval(setup, 6), 24)


  def test_email_account_uses_separate_standard_mail_servers(self):
    account = normalize_account({
        "type": "imap_smtp",
        "name": "Email",
        "username": "person@example.test",
        "imap_host": "imap.example.test",
        "smtp_host": "smtp.example.test",
        "password_ref": "MARCEL_EMAIL_PASSWORD",
    })
    self.assertEqual(account["imap"]["host"], "imap.example.test")
    self.assertEqual(account["smtp"]["host"], "smtp.example.test")
    self.assertEqual(account["smtp"]["password_ref"], "${MARCEL_EMAIL_PASSWORD}")


  def test_brave_search_backend_is_written_to_runtime_config(self):
    config = {}
    values = {
        "agent_name": "Marcel",
        "router_mode": "marcel_router",
        "orchestrator_model": "openai/gpt-5.6-luna",
        "workers": [],
        "accounts": [],
        "memory_maintenance_enabled": True,
        "web_backend": "brave-free",
    }
    apply_marcel_config(config, values)
    self.assertEqual(config["web"]["backend"], "brave-free")


  def test_marcel_soul_uses_the_chosen_agent_name(self):
    soul = build_marcel_soul("TestAgent")
    self.assertIn("You are TestAgent", soul)
    self.assertIn("powered by Marcel", soul)
    self.assertIn("busy CEO", soul)
    self.assertIn("plain everyday language", soul)
    self.assertNotIn("You are Marcel", soul)

  def test_agent_name_is_unicode_normalized_and_control_safe(self):
    self.assertEqual(normalize_agent_name("  Jose\u0301   😀 "), "Jos\u00e9 😀")
    with self.assertRaises(ValueError):
      normalize_agent_name("\u202eunsafe")
    with self.assertRaises(ValueError):
      normalize_agent_name("")

  def test_first_install_name_has_no_default_and_reprompts_on_blank(self):
    class InitialNameSetup:
      def __init__(self):
        self.answers = ["", "Ren\u00e9e"]
        self.prompts = []

      def prompt(self, *args, **_kwargs):
        self.prompts.append(args)
        return self.answers.pop(0)

      def print_error(self, _message):
        return None

      def _info(self, *_messages):
        return None

    setup = InitialNameSetup()
    self.assertEqual(_prompt_agent_name(setup), "Ren\u00e9e")
    self.assertEqual(setup.prompts, [("Agent name",), ("Agent name", "")])

  def test_reconfigure_name_can_leave_blank_to_keep_existing(self):
    class ExistingNameSetup:
      def _info(self, *_messages):
        return None

      def prompt(self, *args, **_kwargs):
        self.prompt_args = args
        return ""

    setup = ExistingNameSetup()
    self.assertEqual(_prompt_agent_name(setup, "Marcel", reconfigure=True), "Marcel")
    self.assertEqual(setup.prompt_args, ("Agent name", ""))

  def test_direct_route_always_shows_explicit_provider_picker(self):
    class ProviderSetup(_SetupStub):
      def __init__(self):
        super().__init__(2)

    setup = ProviderSetup()
    selected = _choose_direct_provider(setup, "")
    self.assertEqual(selected[1], "gemini")
    self.assertEqual(setup.seen_choices, [
      "Anthropic", "OpenAI", "Google Gemini", "xAI Grok",
    ])

  def test_legacy_empty_builder_name_keeps_marcel_compatibility(self):
    result = build_marcel_config({"router_mode": "marcel_router"})
    self.assertEqual(result["agent_name"], "Marcel")
    self.assertEqual(result["orchestrator"]["name"], "Marcel")

  def test_live_router_catalog_labels_image_routes_from_metadata(self):
    live = [
      {"id": "vendor/generator", "metadata": {"capabilities": ["image_generation"]}},
      {"id": "vendor/vision", "metadata": {"capabilities": ["vision"]}},
      {"id": "vendor/unknown", "metadata": {"capabilities": ["chat"]}},
    ]
    catalog = _catalog_for_activity("image", live)
    labels = [label for label, _ in catalog]
    self.assertNotIn("vendor/generator", [model_id for _, model_id in catalog])
    self.assertNotIn("vendor/vision", [model_id for _, model_id in catalog])
    self.assertIn("vendor/unknown", [model_id for _, model_id in catalog])

  def test_available_models_preselect_existing_union_primary_and_fallbacks(self):
    setup = _SetupStub(0)
    selected = _choose_available_models(
      setup,
      MODEL_CHOICES[0][1],
      [MODEL_CHOICES[1][1]],
      current=[MODEL_CHOICES[2][1]],
    )
    self.assertEqual(
      setup.pre_selected,
      [index for index, item in enumerate(MODEL_CHOICES)
       if item[1] in {MODEL_CHOICES[0][1], MODEL_CHOICES[1][1], MODEL_CHOICES[2][1]}],
    )
    self.assertEqual(
      selected,
      [MODEL_CHOICES[2][1], MODEL_CHOICES[0][1], MODEL_CHOICES[1][1]],
    )

  def test_available_models_keeps_existing_id_missing_from_catalog(self):
    setup = _SetupStub(0)
    selected = _choose_available_models(
      setup,
      MODEL_CHOICES[0][1],
      [],
      current=["legacy/custom-model"],
    )
    self.assertIn("legacy/custom-model", selected)
    self.assertTrue(any("Existing/custom" in choice for choice in setup.seen_checklist))

  def test_router_origin_normalization_is_stable(self):
    self.assertEqual(
      _normalized_router_origin("https://Router.Example.test:443/v1/"),
      "https://router.example.test/v1",
    )

  def test_live_router_metadata_keeps_provider_owner_and_preview(self):
    entries = _normalize_router_models({
      "data": [{
        "id": "vendor/vision-preview",
        "owned_by": "vendor",
        "preview": True,
        "metadata": {"capabilities": ["vision"]},
      }],
    })
    self.assertEqual(entries[0]["owned_by"], "vendor")
    self.assertTrue(entries[0]["preview"])

  def test_name_rejects_category_c_before_whitespace_normalization(self):
    for value in ("a\nb", "a\rb", "a\tb", "a\033b", "a\u202eb", "a\u200bb"):
      with self.assertRaises(ValueError):
        normalize_agent_name(value)

  def test_endpoint_transport_policy_is_mode_specific(self):
    with self.assertRaises(ValueError):
      _validate_router_url("http://router.example.test/v1")
    with self.assertRaises(ValueError):
      _validate_custom_endpoint_url("http://router.example.test/v1")
    self.assertEqual(
      _validate_custom_endpoint_url("http://127.0.0.1:8080/v1"),
      "http://127.0.0.1:8080/v1",
    )

  def test_switching_connection_modes_does_not_reuse_router_secret_or_host(self):
    router = {
      "mode": "marcel_router",
      "base_url": "https://router.example.test/v1",
      "key_env": "MARCEL_ROUTER_API_KEY",
    }
    self.assertEqual(
      _mode_connection_defaults(router, "marcel_router", "custom_endpoint"),
      ("", "MARCEL_CUSTOM_API_KEY"),
    )
    self.assertEqual(
      _mode_connection_defaults(router, "marcel_router", "direct_provider"),
      ("", ""),
    )

  def test_generation_catalog_excludes_router_vision_and_unknown_entries(self):
    live = [
      {"id": "vision", "metadata": {"capabilities": ["vision"]}},
      {"id": "unknown", "metadata": {"capabilities": ["chat"]}},
      {"id": "generator", "metadata": {"capabilities": ["image_generation"]}},
    ]
    self.assertEqual(
      [model_id for _, model_id in _generation_catalog(live)],
      ["generator"],
    )

  def test_vision_catalog_requires_explicit_capability_and_stays_separate(self):
    live = [
      {"id": "generator", "metadata": {"capabilities": ["image_generation"]}},
      {"id": "vision", "metadata": {"capabilities": ["vision"]}},
    ]
    self.assertEqual([item[1] for item in _vision_catalog(live)], ["vision"])
    self.assertEqual([item[1] for item in _generation_catalog(live)], ["generator"])

  def test_vision_worker_model_and_fallbacks_are_explicit_vision_only(self):
    live = [
      {"id": "chat", "metadata": {"capabilities": ["chat"]}},
      {"id": "vision", "metadata": {"capabilities": ["chat"], "supports_vision": True}},
    ]
    self.assertEqual(
      [model_id for _, model_id in _fallback_catalog("vision", live)],
      ["vision"],
    )

  def test_registered_image_model_keeps_its_provider(self):
    self.assertEqual(
      _provider_for_selected_model("fal-ai/flux-2/klein/9b", {}, "openai-api"),
      "fal",
    )

  def test_image_worker_serialization_keeps_llm_provider(self):
    config = apply_marcel_config({}, {
      "agent_name": "TestAgent",
      "router_mode": "direct_provider",
      "direct_provider": "openai-api",
      "orchestrator_model": "openai/gpt-5.6-terra",
      "orchestrator_fallback_models": [],
      "workers": [{
        "id": "artist",
        "activity": "image",
        "model": "fal-ai/flux-2/klein/9b",
        "fallbacks": ["fal-ai/flux-2/klein/9b"],
      }],
    })
    self.assertEqual(config["delegation"]["workers"]["artist"]["provider"], "openai-api")

  def test_router_worker_transport_stays_marcel_despite_owned_by_metadata(self):
    config = apply_marcel_config({}, {
      "agent_name": "TestAgent",
      "router_mode": "marcel_router",
      "orchestrator_model": "vendor/chat",
      "orchestrator_fallback_models": [],
      "live_model_entries": [{
        "id": "vendor/chat", "owned_by": "openai",
        "metadata": {"capabilities": ["chat"]},
      }],
      "workers": [{
        "id": "researcher", "activity": "general", "model": "vendor/chat",
      }],
    })
    self.assertEqual(config["delegation"]["workers"]["researcher"]["provider"], "marcel")

  def test_image_generation_worker_uses_llm_and_global_image_service(self):
    config = apply_marcel_config({}, {
      "agent_name": "TestAgent",
      "router_mode": "direct_provider",
      "direct_provider": "openai-api",
      "orchestrator_model": "openai/gpt-5.6-terra",
      "orchestrator_fallback_models": [],
      "workers": [{
        "id": "artist", "activity": "image_generation",
        "model": "openai/gpt-5.6-terra",
      }],
    })
    worker = config["delegation"]["workers"]["artist"]
    self.assertEqual(worker["provider"], "openai-api")
    self.assertEqual(worker["image_service"], "global")
    self.assertIn("image_gen", worker["toolsets"])

  def test_direct_image_generation_worker_uses_provider_scoped_llm_picker(self):
    setup = _SetupStub(0)
    selected = _choose_model(
      setup,
      "Image generation worker LLM",
      activity="image_generation",
      provider="openai-api",
    )
    self.assertTrue(selected.startswith("openai/"))
    self.assertFalse(selected.startswith("fal"))

  def test_fallback_runtime_schema_replaces_legacy_key_in_order(self):
    config = {
      "fallback_model": {"provider": "legacy", "model": "stale"},
    }
    apply_marcel_config(config, {
      "agent_name": "TestAgent",
      "router_mode": "marcel_router",
      "base_url": "https://marcel-agent.com/api/v1",
      "api_key_ref": "MARCEL_ROUTER_API_KEY",
      "orchestrator_model": "demo/primary",
      "orchestrator_fallback_models": ["demo/second", "demo/first"],
      "workers": [],
      "accounts": [],
    })
    self.assertEqual(
      [item["model"] for item in config["fallback_providers"]],
      ["demo/second", "demo/first"],
    )
    self.assertNotIn("stale", str(config))
    self.assertNotIn("fallback_model", config)
    self.assertEqual(
      [item["model"] for item in get_fallback_chain(config)],
      ["demo/second", "demo/first"],
    )

  def test_fallback_order_editor_reorders_selected_models(self):
    class OrderingSetup(_SetupStub):
      def _info(self, *_messages):
        return None

      def print_error(self, _message):
        raise AssertionError("valid order should not error")

      def prompt(self, _label, _default=""):
        return "2,1"

    options = [("First", "one"), ("Second", "two")]
    self.assertEqual(_confirm_fallback_order(OrderingSetup(0), options, [0, 1]), [1, 0])


  def test_marcel_soul_replaces_only_the_untouched_upstream_default(self):
    with TemporaryDirectory() as tmp:
      home = Path(tmp)
      soul = home / "SOUL.md"
      soul.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
      with patch("marcel_cli.config.get_marcel_home", return_value=home):
        self.assertTrue(ensure_marcel_soul())
      self.assertEqual(soul.read_text(encoding="utf-8"), MARCEL_SOUL_MD)

      soul.write_text("My custom personality", encoding="utf-8")
      with patch("marcel_cli.config.get_marcel_home", return_value=home):
        self.assertFalse(ensure_marcel_soul())
      self.assertEqual(soul.read_text(encoding="utf-8"), "My custom personality")