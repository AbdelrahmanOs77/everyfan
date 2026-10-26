# Owner D implementation and final handoff

Source: the user's Master Implementation Plan, sections 8, 9, 11 and 13–14,
interpreted against the merged backend's current API contract. The user reviewed
Step 5 and merged PR #5; this branch starts at `2aa91ff`.

## Delivery slices

1. Typed stream adapter, overlay scheduler and meaningful offline timing tests.
2. React broadcast viewer: Judge mode, real tracking pitch, score/clock, persona
   and language preferences, live/demo controls and player/club selection.
3. Four-way comparison, evidence, measured indices, player badges/ticker, recaps
   and public feed. No browser-derived football statistics.
4. Real Chrome acceptance tests, responsive/RTL/accessibility checks, pinned
   dependencies, frontend CI and Static Web Apps deployment configuration.
5. Deploy the static frontend, verify the exact public origin against backend
   CORS, prepare the test guide, English pitch, video and submission handoff.

All backend gates remain mandatory: Python 3.12 pytest, Pyflakes and the stub
injection gate. Frozen contracts remain unchanged. No new paid model run is
needed to build or verify demo mode.

## Design contract

The screen's job is watching one match through a chosen perspective. The primary
action is Watch demo match; Run live and Break it are equally discoverable but
state their different behavior. A compact broadcast score bug anchors a large
pitch; perspective controls sit beside it, with timed commentary and evidence
below. Comparison and feed are separate views of the same match.

Visual assumptions follow the supplied broadcast-viewer specification: dark ink
surfaces, a restrained grass-green pitch, lime action/accent, white typography,
and actual team colors from metadata. No real-club assets or external fonts.
Use a consistent spacing scale, small radii, visible keyboard focus, adequate
contrast, no decorative gradients or invented statistics. At phone widths the
pitch stays central and all controls stack without horizontal page overflow.
Arabic switches the complete interface to RTL; score/time and raw IDs remain
isolated LTR. Names come from `name_ar`.

## Verification boundaries

- Schedule against tracking/state clock, never an early overlay envelope.
- Reset clears overlays, timeline, badges, metrics and stale async results.
- A single unfiltered socket supports perspective/language/comparison switching.
- Demo and live use separate controls; live ownership tokens stay in memory.
- Evidence and analytics retain server-provided values and timestamps.
- Browser tests use isolated Chrome and an off-mode local API, never Azure models.
- Human mobile-network and Arabic-shell signoff, public video upload and final
  hackathon submission are recorded separately from automated checks.

The deployed API currently allows localhost; its resource is outside the Azure
subscription accessible here. Owner A's CORS update will use the concrete SWA
hostname after frontend deployment. This dependency does not block local work.
