"""
DocCrew — CrewAI crew wiring for DocAgent.

Supported providers (all free / open-source models):
  - deepseek   · DeepSeek V3 (chat) — recommended, $5 free credit
  - groq       · Llama 3.3 70B + DeepSeek R1 distill — free tier
  - mistral    · Mistral Small / open-mistral-7b — free tier
  - cerebras   · Llama 3.3 70B — free tier, fastest
  - ollama     · any local model — zero API key
  - openrouter · free :free models (Llama, Mistral, DeepSeek)
  - together   · Llama 3.3 Turbo / DeepSeek — $1 free credit

LiteLLM routing rules (to avoid 'ModelName' errors):
  - Never mix a LiteLLM provider prefix with a custom base_url.
    Use EITHER the prefix (let LiteLLM route) OR base_url with openai/ prefix.
  - DeepSeek R1 (deepseek-reasoner) returns reasoning_content which
    CrewAI cannot parse — always use deepseek-chat (V3) instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv

load_dotenv()

_CONFIG_DIR = Path(__file__).parent / "config"


def _load_yaml(name: str) -> dict:
    with open(_CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Provider registry ─────────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    name: str
    smart_model: str      # structured output / reasoning tasks
    fast_model: str       # prose writing tasks
    api_key_env: str | None
    notes: str
    # LiteLLM kwargs passed directly to LLM()
    extra_kwargs: dict = field(default_factory=dict)


PROVIDERS: dict[str, ProviderConfig] = {
    # DeepSeek V3 (deepseek-chat) — standard OpenAI-compatible API.
    # Do NOT use deepseek-reasoner here: its reasoning_content field breaks CrewAI.
    "deepseek": ProviderConfig(
        name="DeepSeek",
        smart_model="deepseek/deepseek-chat",
        fast_model="deepseek/deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        notes="$5 free credit · platform.deepseek.com",
    ),
    # Groq serves DeepSeek R1 distill in standard chat format — safe to use.
    "groq": ProviderConfig(
        name="Groq",
        smart_model="groq/deepseek-r1-distill-llama-70b",
        fast_model="groq/llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
        notes="Free · 14,400 req/day · console.groq.com",
    ),
    "mistral": ProviderConfig(
        name="Mistral AI",
        smart_model="mistral/mistral-small-latest",
        fast_model="mistral/open-mistral-7b",
        api_key_env="MISTRAL_API_KEY",
        notes="Free tier · console.mistral.ai",
    ),
    "cerebras": ProviderConfig(
        name="Cerebras",
        smart_model="cerebras/llama-3.3-70b",
        fast_model="cerebras/llama-3.3-70b",
        api_key_env="CEREBRAS_API_KEY",
        notes="Free tier · fastest inference · cloud.cerebras.ai",
    ),
    # Ollama: LiteLLM needs base_url explicitly; model prefix is "ollama/".
    "ollama": ProviderConfig(
        name="Ollama (local)",
        smart_model="ollama/llama3.2",
        fast_model="ollama/llama3.2",
        api_key_env=None,
        notes="Zero API key · local · ollama.com",
        extra_kwargs={"base_url": "http://localhost:11434"},
    ),
    # OpenRouter: LiteLLM handles via prefix; no base_url needed.
    "openrouter": ProviderConfig(
        name="OpenRouter",
        smart_model="openrouter/meta-llama/llama-3.3-70b-instruct:free",
        fast_model="openrouter/meta-llama/llama-3.1-8b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
        notes="Free :free models · openrouter.ai",
    ),
    "together": ProviderConfig(
        name="Together AI",
        smart_model="together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        fast_model="together_ai/meta-llama/Llama-3.2-3B-Instruct-Turbo",
        api_key_env="TOGETHER_API_KEY",
        notes="$1 free credit · api.together.ai",
    ),
}

DEFAULT_PROVIDER = "deepseek"


def get_provider_id() -> str:
    return os.environ.get("DOCAGENT_PROVIDER", DEFAULT_PROVIDER).lower()


# ── LLM factory ───────────────────────────────────────────────────────────────

def _make_llm(model: str, provider: ProviderConfig) -> LLM:
    kwargs: dict[str, Any] = {"model": model}

    # Resolve API key
    if provider.api_key_env:
        api_key = os.environ.get(provider.api_key_env, "").strip()
        if not api_key:
            raise EnvironmentError(
                f"Missing API key: {provider.api_key_env}\n"
                f"Provider: {provider.name}\n"
                f"How to get one: {provider.notes}\n"
                f"Set it in the sidebar or in your .env file."
            )
        kwargs["api_key"] = api_key

    # Ollama model override from env (set by sidebar)
    if model.startswith("ollama/"):
        override = os.environ.get("DOCAGENT_OLLAMA_MODEL", "")
        if override:
            kwargs["model"] = f"ollama/{override}"
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        kwargs["base_url"] = ollama_host

    # Any provider-specific extra kwargs (e.g. Ollama base_url default)
    for k, v in provider.extra_kwargs.items():
        kwargs.setdefault(k, v)

    return LLM(**kwargs)


def build_llms(provider_id: str | None = None) -> tuple[LLM, LLM]:
    """Return (smart_llm, fast_llm) for the chosen provider."""
    pid = (provider_id or get_provider_id()).lower()
    provider = PROVIDERS.get(pid)
    if provider is None:
        raise ValueError(
            f"Unknown provider '{pid}'. "
            f"Valid options: {list(PROVIDERS.keys())}"
        )
    smart = _make_llm(provider.smart_model, provider)
    fast  = _make_llm(provider.fast_model,  provider)
    return smart, fast


def test_connection(provider_id: str | None = None) -> str:
    """
    Send a minimal ping to the provider and return 'ok' or an error message.
    Called from the Streamlit sidebar before the full crew run.
    """
    try:
        smart, _ = build_llms(provider_id)
        resp = smart.call([{"role": "user", "content": "Reply with just: ok"}])
        return "ok"
    except Exception as exc:
        return str(exc)


# ── Crew ──────────────────────────────────────────────────────────────────────

class DocCrew:
    def __init__(self, intake: dict[str, Any], provider_id: str | None = None) -> None:
        self.intake = intake
        self.intake_json = json.dumps(intake, indent=2, default=str)
        self.provider_id = (provider_id or get_provider_id()).lower()

    def _build_agents(self, agents_cfg: dict) -> dict[str, Agent]:
        smart_llm, fast_llm = build_llms(self.provider_id)
        # Agents that need precise structured JSON output → smart model
        smart_agents = {"researcher", "strategist", "agent_optimizer", "reviewer", "assembler"}
        agents: dict[str, Agent] = {}
        for key, cfg in agents_cfg.items():
            agents[key] = Agent(
                role=cfg["role"],
                goal=cfg["goal"],
                backstory=cfg["backstory"],
                allow_delegation=cfg.get("allow_delegation", False),
                verbose=cfg.get("verbose", True),
                llm=smart_llm if key in smart_agents else fast_llm,
            )
        return agents

    def _build_tasks(self, tasks_cfg: dict, agents: dict[str, Agent]) -> list[Task]:
        intake = self.intake
        vars_ = {
            "intake_json": self.intake_json,
            "tone": intake.get("tone", "Friendly"),
            "skill_level": intake.get("skill_level", "Intermediate"),
            "code_style": intake.get("code_style", "Full working examples"),
        }
        order = [
            "research_task", "strategy_task",
            "tutorial_task", "howto_task", "reference_task", "explanation_task",
            "agent_optimization_task", "review_task", "assembly_task",
        ]
        skip: set[str] = set()
        if not intake.get("gen_tutorial"):    skip.add("tutorial_task")
        if not intake.get("gen_howto"):       skip.add("howto_task")
        if not intake.get("gen_reference"):   skip.add("reference_task")
        if not intake.get("gen_explanation"): skip.add("explanation_task")
        if not intake.get("agent_friendly"):  skip.add("agent_optimization_task")

        return [
            Task(
                description=tasks_cfg[k]["description"].format(**vars_),
                expected_output=tasks_cfg[k]["expected_output"],
                agent=agents[tasks_cfg[k]["agent"]],
            )
            for k in order if k not in skip and k in tasks_cfg
        ]

    def run(self) -> dict[str, Any]:
        agents_cfg = _load_yaml("agents.yaml")
        tasks_cfg  = _load_yaml("tasks.yaml")
        agents = self._build_agents(agents_cfg)
        tasks  = self._build_tasks(tasks_cfg, agents)
        crew   = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )
        return self._parse_final_output(crew.kickoff())

    @staticmethod
    def _parse_final_output(raw) -> dict[str, Any]:
        text = raw.raw if hasattr(raw, "raw") else str(raw)
        if isinstance(text, dict):
            result = text
        else:
            text = text.strip()
            if text.startswith("```"):
                text = "\n".join(text.splitlines()[1:-1])
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = {
                    "files": {"docs/raw_output.md": text},
                    "manifest": {"qa_status": "parse_error"},
                }
        result.setdefault("files", {})
        result.setdefault("manifest", {})
        return result
