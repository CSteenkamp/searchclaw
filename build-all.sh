#!/bin/bash
set -e
cd /tmp/searchclaw

# Spec 1
echo "=== Starting Spec 1 ==="
claude --dangerously-skip-permissions -p "Read spec-kit/spec-1-foundation.md and PROJECT-SPEC.md. Build everything in Spec 1. The SearchClaw source is at /tmp/searchclaw/ and ScrapeClaw source is at /tmp/scrapeclaw/. Copy and adapt as described. Run all tests. Commit with message 'feat: spec 1 - unified foundation, search, auth (from SearchClaw base)'. Then push to origin master.

When completely finished, print SPEC1_DONE."

if ! git log --oneline -1 | grep -q "spec 1"; then
  echo "ERROR: Spec 1 commit not found. Aborting."
  openclaw system event --text "Error: SearchClaw Spec 1 didn't commit successfully. Build aborted." --mode now
  exit 1
fi

openclaw system event --text "SearchClaw progress: Spec 1 complete — unified foundation with search + auth. Starting Spec 2 (extraction)." --mode now

# Spec 2
echo "=== Starting Spec 2 ==="
claude --dangerously-skip-permissions -p "Read spec-kit/spec-2-extraction.md and PROJECT-SPEC.md. Spec 1 is already built. Build everything in Spec 2. The ScrapeClaw source to integrate from is at /tmp/scrapeclaw/. Do NOT rewrite spec 1 files unless needed for integration. Run all tests (existing + new). Commit with message 'feat: spec 2 - extraction, crawl, markdown, screenshot (from ScrapeClaw)'. Then push to origin master.

When completely finished, print SPEC2_DONE."

if ! git log --oneline -1 | grep -q "spec 2"; then
  echo "ERROR: Spec 2 commit not found. Aborting."
  openclaw system event --text "Error: SearchClaw Spec 2 didn't commit successfully. Spec 3 aborted." --mode now
  exit 1
fi

openclaw system event --text "SearchClaw progress: Spec 2 complete — browser pool, extraction, crawl, markdown, screenshot integrated. Starting Spec 3 (pipeline + dashboard + K8s)." --mode now

# Spec 3
echo "=== Starting Spec 3 ==="
claude --dangerously-skip-permissions -p "Read spec-kit/spec-3-pipeline-dashboard-k8s.md and PROJECT-SPEC.md. Specs 1-2 are already built. Build everything in Spec 3. Do NOT rewrite existing files unless needed for integration. Run all tests (existing + new). Commit with message 'feat: spec 3 - pipeline endpoint, dashboard, SDK, K8s, CI/CD'. Then push to origin master.

When completely finished, print SPEC3_DONE."

if ! git log --oneline -1 | grep -q "spec 3"; then
  echo "ERROR: Spec 3 commit not found."
  openclaw system event --text "Error: SearchClaw Spec 3 didn't commit successfully." --mode now
  exit 1
fi

openclaw system event --text "🏁 SearchClaw fully built! All 3 specs complete — unified search+scrape API with pipeline endpoint, dashboard, SDK, K8s, CI/CD. Repo: github.com/CSteenkamp/searchclaw" --mode now
echo "=== ALL SEARCHCLAW SPECS COMPLETE ==="
