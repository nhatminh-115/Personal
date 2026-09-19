import re
from typing import Dict, List, Optional
from app.research.models import ResearchSource, SourceStatus
from app.research.provider import ResearchSourceProvider


class ResearchCorpusEngine(ResearchSourceProvider):
    """Provides indexed literature search and document section retrieval for deterministic testing."""

    def __init__(self) -> None:
        self._corpus: Dict[str, ResearchSource] = {}
        self._populate_standard_corpus()

    def _populate_standard_corpus(self) -> None:
        # Paper 1: Close Overlap (Stateful memory, but ephemeral/lacks durable crash checkpointing)
        p1 = ResearchSource(
            source_id="src_stateful_graph_2023",
            canonical_id="arxiv:2308.1001",
            title="Stateful Multi-Turn Agent Workflows via In-Memory Graphs",
            authors=["Alice Chen", "Bob Davis"],
            year=2023,
            url="https://arxiv.org/abs/2308.1001",
            venue="arXiv preprint",
            abstract=(
                "We present a framework for managing conversation state across multi-turn agent runs "
                "using in-memory directed graphs. The framework coordinates agent reasoning, tool execution, "
                "and memory integration across sequential user turns."
            ),
            sections={
                "abstract": (
                    "We present a framework for managing conversation state across multi-turn agent runs "
                    "using in-memory directed graphs. The framework coordinates agent reasoning, tool execution, "
                    "and memory integration across sequential user turns."
                ),
                "introduction": (
                    "Traditional conversational agents suffer from context fragmentation. "
                    "We propose a graph-based state container that tracks message history and intermediate tool outputs."
                ),
                "related_work": (
                    "Previous agent architectures primarily maintain linear conversation logs or stateless reactive loops."
                ),
                "methods": (
                    "Our method maintains an active execution graph in memory with volatile node state transitions. "
                    "State is updated dynamically after each tool observation. Notably, state management is ephemeral: "
                    "all graph nodes reside purely in memory and do not implement persistent crash-safe database "
                    "checkpointing or per-tool human approval interruptions."
                ),
                "experiments": "Evaluated on 50 multi-step coding benchmarks across varied complexity.",
                "results": "Achieved 18% improvement in multi-turn consistency compared to raw conversation buffers.",
                "limitations": (
                    "The system cannot survive process termination or server crashes; in-flight workflows are lost upon crash. "
                    "Furthermore, it assumes fully autonomous execution without interactive human authorization gates."
                ),
            },
            status=SourceStatus.CANDIDATE,
            relevance_score=0.92,
            metadata={"topic": "stateful_agents", "doi": "10.48550/arXiv.2308.1001", "fixture": True, "provider": "deterministic_corpus"},
        )

        # Paper 2: Complementary Prior Art (Durable checkpoints, but for automated batch pipelines, no human approvals)
        p2 = ResearchSource(
            source_id="src_pipeline_checkpoint_2024",
            canonical_id="arxiv:2401.5502",
            title="Fault-Tolerant Pipeline Checkpointing for Distributed Language Agents",
            authors=["Carlos Mendez", "Elena Rostova"],
            year=2024,
            url="https://arxiv.org/abs/2401.5502",
            venue="ICSE Workshop on Autonomous Systems",
            abstract=(
                "This paper introduces durable checkpointing for distributed LLM pipelines using transactional "
                "write-ahead logs, enabling recovery from hardware and network failures."
            ),
            sections={
                "abstract": (
                    "This paper introduces durable checkpointing for distributed LLM pipelines using transactional "
                    "write-ahead logs, enabling recovery from hardware and network failures."
                ),
                "introduction": (
                    "Long-running autonomous agent pipelines frequently encounter network partitions and hardware faults. "
                    "Durable state storage is essential for enterprise reliability."
                ),
                "methods": (
                    "The architecture implements transactional write-ahead checkpoints for sequential batch pipelines. "
                    "Execution state is persisted to a durable datastore at stage boundaries. However, the design is strictly "
                    "oriented toward automated batch pipelines; it does not support fine-grained per-tool human approval "
                    "gates or interactive suspension/resume mechanisms."
                ),
                "results": "Demonstrated 99.4% crash recovery rate across 10,000 simulated fault injections.",
                "limitations": (
                    "Batch-only orientation: lacking interactive human-in-the-loop approval workflows and conversational "
                    "context memory integration."
                ),
            },
            status=SourceStatus.CANDIDATE,
            relevance_score=0.85,
            metadata={"topic": "checkpointing", "doi": "10.48550/arXiv.2401.5502", "fixture": True, "provider": "deterministic_corpus"},
        )

        # Paper 3: Irrelevant distractor (Pruning transformer attention, completely different domain)
        p3 = ResearchSource(
            source_id="src_transformer_pruning_2022",
            canonical_id="arxiv:2203.9999",
            title="Transformer Attention Pruning for Efficient Matrix Multiplication",
            authors=["David Kim", "Fiona Gallagher"],
            year=2022,
            url="https://arxiv.org/abs/2203.9999",
            venue="NeurIPS Workshop",
            abstract="We propose structured pruning techniques for self-attention weight matrices to accelerate hardware inference.",
            sections={
                "abstract": "We propose structured pruning techniques for self-attention weight matrices to accelerate hardware inference.",
                "methods": "Pruning 40% of attention heads using L1-norm magnitude thresholding.",
                "results": "Speedup of 1.4x with minimal perplexity degradation.",
                "limitations": "Limited to dense transformer decoders; does not address agent execution or memory.",
            },
            status=SourceStatus.CANDIDATE,
            relevance_score=0.20,
            metadata={"topic": "model_compression", "fixture": True, "provider": "deterministic_corpus"},
        )

        self._corpus[p1.source_id] = p1
        self._corpus[p2.source_id] = p2
        self._corpus[p3.source_id] = p3

    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Perform keyword search across titles, abstracts, and metadata."""
        return self._search_sync(query, search_type=search_type, max_results=max_results)

    def _search_sync(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
        scored: List[tuple[float, ResearchSource]] = []

        for src in self._corpus.values():
            text = f"{src.title} {src.abstract or ''} {src.sections.get('methods', '')}".lower()
            score = 0.0
            for t in tokens:
                if t in src.title.lower():
                    score += 3.0
                elif t in text:
                    score += 1.0

            # Normalize by initial relevance if matched
            if score > 0:
                final_score = min(1.0, (score / 10.0) * src.relevance_score)
                # Clone source to avoid mutating corpus singleton state
                cloned = src.model_copy(deep=True)
                cloned.relevance_score = round(final_score, 2)
                scored.append((final_score, cloned))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:max_results]]

    def get_source(self, source_id: str) -> Optional[ResearchSource]:
        src = self._corpus.get(source_id)
        return src.model_copy(deep=True) if src else None

    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        return self.get_source(source_id)

    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        src = self._corpus.get(source_id)
        if not src:
            return None
        return src.sections.get(section_name.lower())

    def add_source(self, source: ResearchSource) -> None:
        self._corpus[source.source_id] = source


# Alias for test clarity
DeterministicResearchProvider = ResearchCorpusEngine

# Singleton global corpus engine
corpus_engine = ResearchCorpusEngine()
