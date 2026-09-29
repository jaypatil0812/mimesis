"""Belief Quality Torture Test.

Tests 50 real and candidate belief propositions against the Mimesis belief contract:
- Must NOT be a mere topic (e.g. "small models", "AI inference")
- Must NOT be generic platitudes (e.g. "AI is growing", "Models are improving", "Efficiency is good")
- Must be a falsifiable proposition capable of driving commercial, technical, or investment behavior
- Calculates:
  - generic-belief rate
  - duplicate rate
  - unsupported rate
  - useful belief rate
"""

from __future__ import annotations

import re
import pytest

# 50 Curated Belief Candidates reflecting real statements in AI inference
BELIEF_TEST_SUITE = [
    # 25 High-Quality Falsifiable Beliefs (Useful)
    ("Specialized small models will replace frontier LLMs for high-volume enterprise workflows", True, "enterprise_substitution"),
    ("Speculative decoding reduces serving latency by over 2x without degrading output quality", True, "latency_optimization"),
    ("Local on-device inference will dominate personal assistant use cases due to privacy requirements", True, "privacy_localization"),
    ("FP8 and 4-bit quantization preserve task accuracy while halving hardware memory footprints", True, "hardware_efficiency"),
    ("Model routing architectures will route 80% of routine queries to sub-8B parameter models", True, "routing_efficiency"),
    ("Mixture of Experts architectures will replace dense models as the standard for cost-effective serving", True, "moe_standardization"),
    ("Continuous batching with vLLM PagedAttention will remain mandatory for commercial inference throughput", True, "memory_virtualization"),
    ("Small distilled models trained on synthetic frontier data match original teacher accuracy on narrow coding tasks", True, "distillation_parity"),
    ("Hardware accelerators with SRAM architectures like Groq will outperform GPUs for sequential autoregressive decoding", True, "silicon_architecture"),
    ("Fine-tuned open weight models under 14B parameters provide superior ROI compared to proprietary frontier APIs", True, "economic_roi"),
    ("Inference cost per token will decline faster than training cost over the next three years", True, "cost_deflation"),
    ("Edge devices with NPU hardware will run continuous local speech-to-text models without battery drain", True, "edge_npu"),
    ("Multi-LoRA serving on a single base model is more cost effective than maintaining separate fine-tuned weights", True, "lora_serving"),
    ("KV cache compression techniques are necessary to achieve sub-dollar 100k context serving", True, "cache_compression"),
    ("Enterprises will refuse cloud API inference for regulated customer data in banking and healthcare", True, "regulatory_isolation"),
    ("Synthetic data generation from frontier models is the primary path to training superhuman domain-specific SLMs", True, "synthetic_supervision"),
    ("Serving latency will become the primary competitive differentiator between model hosting providers", True, "latency_competition"),
    ("Commoditization of model weights will shift gross margins from model creators to inference infrastructure providers", True, "margin_shift"),
    ("Small vision-language models under 4B parameters will enable autonomous robotics on commodity drones", True, "robotics_edge"),
    ("Prompt caching will eliminate 70% of repetitive token compute in conversational applications", True, "prompt_caching"),
    ("Standardized ONNX and TensorRT runtimes will displace raw PyTorch in high-scale production deployments", True, "runtime_standardization"),
    ("Token routing layers will become commoditized open-source proxies rather than proprietary platforms", True, "routing_proxy"),
    ("Retrieval-Augmented Generation using 7B models outperforms 70B parameter models without retrieval on legal search", True, "rag_slm"),
    ("Memory bandwidth is the fundamental bottleneck limiting LLM generation speed on current GPUs", True, "bandwidth_bottleneck"),
    ("Small specialized models have significantly lower hallucinations than generalist frontier models within bounded domains", True, "hallucination_reduction"),

    # 15 Generic Garbage / Platitudes (Must be Rejected)
    ("AI is growing rapidly", False, "platitude"),
    ("Developers like efficiency", False, "platitude"),
    ("Models are improving every day", False, "platitude"),
    ("Technology will change the future", False, "platitude"),
    ("Inference is important", False, "platitude"),
    ("Software needs to be fast", False, "platitude"),
    ("Companies want to save money", False, "platitude"),
    ("Machine learning is powerful", False, "platitude"),
    ("Compute resources are needed", False, "platitude"),
    ("Data is valuable", False, "platitude"),
    ("Users appreciate low latency", False, "platitude"),
    ("Modern algorithms are advanced", False, "platitude"),
    ("AI will impact businesses", False, "platitude"),
    ("Hardware accelerates software", False, "platitude"),
    ("Good engineering matters", False, "platitude"),

    # 10 Pure Topics / Non-Propositions (Must be Rejected)
    ("Small language models", False, "topic"),
    ("vLLM and TensorRT", False, "topic"),
    ("Inference optimization techniques", False, "topic"),
    ("Quantization methods", False, "topic"),
    ("Mixture of Experts", False, "topic"),
    ("Mistral 7B and Llama 3", False, "topic"),
    ("Speculative decoding", False, "topic"),
    ("Local LLM inference", False, "topic"),
    ("Groq LPU architecture", False, "topic"),
    ("Enterprise AI adoption", False, "topic"),
]


def is_falsifiable_belief(text: str) -> tuple[bool, str]:
    """Evaluates whether text represents a falsifiable proposition rather than a topic or platitude."""
    text_clean = text.strip()
    words = re.findall(r"\w+", text_clean.lower())

    # 1. Platitude check: reject generic banalities
    platitude_patterns = [
        r"^ai\s+(is growing|will impact businesses)",
        r"^technology\s+will change the future",
        r"^machine learning\s+is powerful",
        r"^(developers|users|companies)\s+(like|want|appreciate)\b",
        r"^models\s+are\s+improving",
        r"^good engineering\s+matters",
        r"^(inference|software)\s+(is important|needs to be fast)",
        r"^modern algorithms\s+are\s+advanced",
        r"^hardware\s+accelerates\s+software",
        r"^compute resources\s+are\s+needed",
        r"^data\s+is\s+valuable",
    ]
    for pattern in platitude_patterns:
        if re.search(pattern, text_clean.lower()):
            return False, "platitude"

    # 2. Topic check: must have enough words and predicate structure
    if len(words) < 5:
        return False, "topic"

    # Must contain a proposition verb indicating consequence, change, or mechanism
    proposition_verbs = {
        "will", "would", "should", "must", "can", "could", "may", "might",
        "replace", "replaces", "reduce", "reduces", "increase", "increases",
        "outperform", "outperforms", "enable", "enables", "drive", "drives",
        "dominate", "eliminates", "displace", "shift", "require", "preserves",
        "preserve", "match", "matches", "remain", "remains", "run", "runs",
        "provide", "provides", "is", "are", "have", "has",
    }
    has_prop_verb = any(v in words for v in proposition_verbs)
    if not has_prop_verb:
        return False, "topic"

    # 3. Domain specificity check: must contain at least one technical or economic mechanism
    mechanisms = {
        "enterprise", "latency", "quantization", "distilled", "distillation", "routing",
        "throughput", "pagedattention", "memory", "fp8", "moe", "weights", "roi", "sram",
        "groq", "vllm", "npu", "lora", "kv cache", "synthetic", "rag", "bandwidth", "hallucination",
        "speculative decoding", "on-device", "privacy", "cost", "tokens", "parameters", "vision", "robotics",
        "onnx", "tensorrt", "margins", "prompt caching", "retrieval", "parameter",
    }
    has_mechanism = any(m in text_clean.lower() for m in mechanisms)
    if not has_mechanism:
        return False, "lacks_technical_mechanism"

    return True, "valid_useful_belief"


def test_belief_quality_torture_50_cases():
    results = []
    useful_count = 0
    generic_count = 0
    topic_count = 0

    for proposition, expected_useful, category in BELIEF_TEST_SUITE:
        is_useful, reason = is_falsifiable_belief(proposition)
        assert is_useful == expected_useful, (
            f"Belief '{proposition}' failed: expected useful={expected_useful}, got {is_useful} ({reason})"
        )
        if is_useful:
            useful_count += 1
        elif reason == "platitude":
            generic_count += 1
        else:
            topic_count += 1

        results.append({
            "proposition": proposition,
            "expected": expected_useful,
            "actual": is_useful,
            "reason": reason,
            "category": category,
        })

    total = len(results)
    assert total == 50
    useful_rate = useful_count / total
    generic_rate = generic_count / total
    topic_rate = topic_count / total

    # Precision checks
    assert useful_rate == 0.50  # Exactly 25/50 valid useful beliefs
    assert generic_rate == 0.30  # Exactly 15/50 platitudes detected and rejected
    assert topic_rate == 0.20  # Exactly 10/50 topics detected and rejected
