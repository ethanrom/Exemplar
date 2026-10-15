"""Active learning (stream E, PLAN.md §2.4): a committee over the rule version space and query selection.

    committee = build_committee(candidates, examples)               # candidates: exemplar.synth.Candidate
    [q] = select_query(committee, unlabelled_traces, labelled=labelled_traces)
    q.to_api(concept_id="c1")                                        # api.yaml Question

Labels obtained this way have provenance 'active': used for synthesis, never for calibration.
"""
from .committee import Committee, build_committee
from .query import Question, committee_scores, select_query

__all__ = ["Committee", "Question", "build_committee", "committee_scores", "select_query"]
