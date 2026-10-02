"""Domain-neutral lexical hints. A missing match is not semantic disproof."""
import re

VERSION = "query-relevance-v1"
STOP = frozenset("the and are what which who about for with from that this these those how does do did can could would should will have has was were is it its next big thing market markets tell me evidence show happening".split())


def terms(text):
    return {word for word in re.findall(r"[^\W_]+", str(text).casefold()) if len(word) > 2 and word not in STOP}


def overlap(query, text):
    query_terms = terms(query)
    return len(query_terms & terms(text)) / max(len(query_terms), 1)
