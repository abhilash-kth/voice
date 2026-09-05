"""Seed/default config used when no agent is explicitly selected (demo fallback)."""
from __future__ import annotations

from .models import AgentConfig, ProviderSelection, ProviderPair, KnowledgeBase


def default_config(agent_id: str = "demo") -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        name="Kavya",
        description="Default Kriscent Techno Hub receptionist",
        greeting=(
            "Namaste! Main Kavya hoon, Kriscent Techno Hub ki AI assistant. "
            "Aap humari IT services ya software products ke baare mein pooch sakte hain. "
            "Bataiye main kya madad karoon?"
        ),
        providers=ProviderSelection(
            llm=ProviderPair(
                id="groq_llama_3_3_70b",
                config={"model": "llama-3.3-70b-versatile", "temperature": 0.1},
            ),
            stt=ProviderPair(id="deepgram_nova2", config={"language": "hi"}),
            tts=ProviderPair(id="google_wavenet_hi", config={"voice": "hi-IN-Chirp3-HD-Leda"}),
            telephony=ProviderPair(id="browser", config={}),
        ),
        knowledge=KnowledgeBase(
            text=(
                "Kriscent Techno Hub is an IT company in Kota, Rajasthan that builds "
                "software, mobile apps and AI solutions. Founded by Mr. Kapil Gautam "
                "in 2014. Products include K-Smart CRM, K-Exam, Prabal and HRMS."
            ),
            system_prompt=(
                "If asked about company and location together, answer both in one "
                "short sentence. If the user asks for contact/number, ask for their "
                "number and say the team will call back."
            ),
        ),
        language="hi",
        voice_personality="friendly",
        client_rate_per_min=2.50,
        enabled=True,
    )
