"""Contract tests for the tracking-aware research manifest v4."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import company_view
import events_digest
import portfolio_formation
import research_feed


class ResearchFeedV4Tests(unittest.TestCase):
    @staticmethod
    def _entry(*, completed: bool, tracked: bool = True, ended: bool = False) -> dict:
        packet = {
            "path": "published/alpha/",
            "version": 2,
            "content_hash": "sha256:packet",
        } if completed else None
        return {
            "slug": "alpha",
            "company_id": "IN:ALPHA",
            "ticker": "ALPHA",
            "market": "IN",
            "name": "Alpha Ltd",
            "listed": True,
            "coverage": (
                {
                    "status": "Ended",
                    "ended_on": "2026-07-19",
                    "reason": "The approved evidence baseline is no longer maintainable.",
                }
                if ended
                else ({"status": "Active", "ended_on": None, "reason": None} if completed else None)
            ),
            "recommendation": {"value": "Invest — evidence supports ownership"} if completed else None,
            "why": "Evidence remains supportive." if completed else None,
            "thesis": {"statement": "A thesis.", "assumptions": []} if completed else None,
            "valuation": None,
            "packet": packet,
            "tracking": {
                "reviewed": True,
                "globally_tracked": tracked,
                "relationships": [{
                    "key": "sector:test-india:IN:ALPHA",
                    "scope": "sector",
                    "sector_slug": "test-india",
                    "state": "Tracked" if tracked else "Untracked",
                    "reason": "Approved relationship.",
                    "decision_date": "2026-07-18",
                }],
            },
            "research_status": "Completed" if completed else "Not yet assessed",
            "record_hash": "sha256:" + ("a" if completed else "b") * 64,
        }

    def test_classification_preserves_client_relation_tracking_and_research_status(self) -> None:
        row = research_feed.classify(
            [self._entry(completed=False)],
            held={("india", "ALPHA")},
            watched=set(),
            seen={},
            schema_version=4,
        )[0]
        self.assertEqual(row["relation"], "HELD")
        self.assertTrue(row["tracking"]["globally_tracked"])
        self.assertEqual(row["research_status"], "Not yet assessed")
        self.assertEqual(row["revision"], "sha256:" + "b" * 64)

    def test_tracking_only_row_is_never_sized_or_called_covered(self) -> None:
        row = research_feed.classify(
            [self._entry(completed=False)], set(), set(), {}, schema_version=4
        )[0]
        outcome, conviction, _reason = portfolio_formation.first_cut(row)
        self.assertEqual((outcome, conviction), ("not_assessed", ""))
        proposal = portfolio_formation.build_proposal(
            [row], {"max_per_stock": 0.10}, {}, set()
        )
        self.assertIsNone(proposal["rows"][0]["target_pct"])
        target = company_view.resolve_target("ALPHA", [row], set(), set(), "default")
        self.assertFalse(target["covered"])
        self.assertEqual(target["research_status"], "Not yet assessed")

    def test_events_include_tracked_unassessed_but_exclude_untracked_unassessed(self) -> None:
        tracked = research_feed.classify(
            [self._entry(completed=False, tracked=True)], set(), set(), {}, schema_version=4
        )[0]
        untracked_entry = self._entry(completed=False, tracked=False)
        untracked_entry["slug"] = "beta"
        untracked_entry["ticker"] = "BETA"
        untracked_entry["company_id"] = "IN:BETA"
        untracked_entry["tracking"]["relationships"][0]["key"] = "sector:test-india:IN:BETA"
        untracked = research_feed.classify(
            [untracked_entry], set(), set(), {}, schema_version=4
        )[0]
        universe = events_digest.build_universe([tracked, untracked], set(), set())
        self.assertIn(("india", "ALPHA"), universe)
        self.assertNotIn(("india", "BETA"), universe)
        self.assertFalse(universe[("india", "ALPHA")]["covered"])
        self.assertIn("not assessed", events_digest._tag(universe[("india", "ALPHA")]))
        digest = events_digest.build_digest(
            universe,
            {"alpha": {"upcoming": [], "errors": []}},
            "2026-07-18",
            90,
        )
        self.assertIn("1 research-tracked without active coverage", digest)

    def test_completed_row_retains_packet_behavior(self) -> None:
        row = research_feed.classify(
            [self._entry(completed=True)], set(), set(), {}, schema_version=4
        )[0]
        outcome, _conviction, _reason = portfolio_formation.first_cut(row)
        self.assertEqual(outcome, "back_now")
        target = company_view.resolve_target("ALPHA", [row], set(), set(), "default")
        self.assertTrue(target["covered"])

    def test_v4_entry_without_explicit_research_status_fails_closed(self) -> None:
        entry = self._entry(completed=False)
        del entry["research_status"]
        with self.assertRaisesRegex(ValueError, "no valid research_status"):
            research_feed.classify([entry], set(), set(), {}, schema_version=4)

    def test_v4_tracking_block_and_unresearched_fields_fail_closed(self) -> None:
        entry = self._entry(completed=False)
        entry["tracking"]["globally_tracked"] = False
        with self.assertRaisesRegex(ValueError, "invalid tracking block"):
            research_feed.classify([entry], set(), set(), {}, schema_version=4)

        entry = self._entry(completed=False)
        entry["valuation"] = {"zone": "FAIR"}
        with self.assertRaisesRegex(ValueError, "fabricated research"):
            research_feed.classify([entry], set(), set(), {}, schema_version=4)

    def test_obsolete_and_future_schemas_are_rejected(self) -> None:
        entry = self._entry(completed=True)
        for schema_version in (3, 5):
            with self.assertRaisesRegex(ValueError, "unsupported manifest schema_version"):
                research_feed.classify([entry], set(), set(), {}, schema_version=schema_version)

    def test_untracked_pending_row_is_not_described_as_active_tracking(self) -> None:
        row = research_feed.classify(
            [self._entry(completed=False, tracked=False)], set(), set(), {}, schema_version=4
        )[0]
        outcome, conviction, reason = portfolio_formation.first_cut(row)
        self.assertEqual((outcome, conviction), ("untracked", ""))
        self.assertIn("chose not to track", reason)
        proposal = portfolio_formation.build_proposal(
            [row], {"max_per_stock": 0.10}, {}, set()
        )
        self.assertIsNone(proposal["rows"][0]["target_pct"])
        target = company_view.resolve_target("ALPHA", [row], set(), set(), "default")
        header = "\n".join(company_view._fmt_header(target))
        self.assertIn("chose not to track", header)
        self.assertNotIn("tracks this relationship", header)

    def test_explicit_coverage_ending_alerts_once_and_is_never_sized(self) -> None:
        entry = self._entry(completed=True, ended=True)
        prior_revision = "sha256:" + "c" * 64
        row = research_feed.classify(
            [entry], set(), set(), {"alpha": prior_revision}, schema_version=4
        )[0]

        self.assertEqual((row["research_status"], row["change"]), ("Completed", "UPDATED"))
        self.assertEqual(row["coverage"]["status"], "Ended")
        outcome, conviction, reason = portfolio_formation.first_cut(row)
        self.assertEqual((outcome, conviction), ("coverage_ended", ""))
        self.assertIn("coverage ended 2026-07-19", reason)
        proposal = portfolio_formation.build_proposal([row], {"max_per_stock": 0.10}, {}, set())
        self.assertIsNone(proposal["rows"][0]["target_pct"])
        held = {("india", "ALPHA")}
        self.assertEqual(portfolio_formation.legacy_holdings([row], held), [("india", "ALPHA")])
        self.assertEqual(portfolio_formation.coverage_requests([row], held, held), ([], []))
        target = company_view.resolve_target("ALPHA", [row], set(), set(), "default")
        self.assertFalse(target["covered"])
        self.assertIn("coverage ended 2026-07-19", "\n".join(company_view._fmt_header(target)))
        universe = events_digest.build_universe([row], set(), set())
        self.assertIn(("india", "ALPHA"), universe)
        self.assertIn("coverage ended", events_digest._tag(universe[("india", "ALPHA")]))

        report = research_feed.format_report([row], "default", "2026-07-19")
        self.assertEqual(report.count("COVERAGE ENDED 2026-07-19"), 1)
        seen_row = research_feed.classify(
            [entry], set(), set(), {"alpha": row["revision"]}, schema_version=4
        )[0]
        self.assertEqual(seen_row["change"], "UNCHANGED")
        seen_report = research_feed.format_report([seen_row], "default", "2026-07-19")
        self.assertNotIn("COVERAGE ENDED 2026-07-19  [UPDATED]", seen_report)

    def test_manifest_cannot_silently_drop_seen_research(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit Ended tombstone"):
            research_feed.classify(
                [], set(), set(), {"alpha": "sha256:" + "a" * 64}, schema_version=4
            )

    def test_held_ended_name_keeps_ending_context_without_research_tracking(self) -> None:
        entry = self._entry(completed=True, tracked=False, ended=True)
        held = {("india", "ALPHA")}
        row = research_feed.classify([entry], held, set(), {}, schema_version=4)[0]
        universe = events_digest.build_universe([row], held, set())

        self.assertIn(("india", "ALPHA"), universe)
        self.assertEqual(universe[("india", "ALPHA")]["relation"], "HELD")
        self.assertIn("coverage ended", events_digest._tag(universe[("india", "ALPHA")]))

    def test_ended_research_requires_a_valid_coverage_block(self) -> None:
        entry = self._entry(completed=True, ended=True)
        entry["coverage"]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "invalid coverage block"):
            research_feed.classify([entry], set(), set(), {}, schema_version=4)


if __name__ == "__main__":
    unittest.main()
