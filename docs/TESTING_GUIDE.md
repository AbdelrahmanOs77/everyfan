# Try EveryFan

The public frontend URL is pending Azure region/account access; see
[Owner D deployment status](OWNER_D.md#azure-deployment-dependency).
For local access follow [Owner D setup](OWNER_D.md#local-setup), then open
http://localhost:5173. All clubs, players and matches are fictional.

1. Select **Watch demo match**. It plays recorded, verified agent/template output
   without calling a model. Click a goal in **Key moments** to jump there. The
   replay pauses at goals so you can explore; use Play to continue, or uncheck
   **Pause at goals** for a continuous match. Speeds range from 1× to 60×.
2. Use the top **Beginner**, **Tactical**, **Player**, and **My club** buttons.
   Each opens its own fan interface and selects the matching commentary persona.
   Use **Compare perspectives** below the interface to see Beginner, Tactical,
   Player Focus and Arabic describe
   the same play. Highlight navigation selects that moment's player so Player
   Focus has the matching perspective. Facts remain supplied by the backend.
3. Select **Inspect evidence** on a card. Read the measured facts, detection rule
   and linked source events. Copy the workflow trace ID if one is present.
4. Open **Judge Lab**, then select **Break it**. An intentionally invented `999999` is shown as a rejected
   draft beside the checked replacement. The draft never enters the broadcast;
   this demonstration does not call a model. The comparison appears directly in
   Judge Lab. Use a fan button in the top navigation to return to its interface.
5. Switch **Commentary language** to **العربية**. The interface and cards become
   RTL; names come from Arabic metadata. Try **Player** and select a player,
   or **My club** and select your side. Choices survive refresh.
6. In **Tactical**, choose a team and a one-, five- or fifteen-minute window, or
   the match so far. Inspect rates against the match baseline, PPDA components,
   **Passing & territory**, and **Shots & actions**. In **Player**, explore the
   individual's contributions, physical performance and shot evidence. Open
   **Match story** for a recap so far, or at full time for the final recap.
   Open **Overlay feed** for published cards, search/perspective filters, raw JSON
   and JSON Schema. Every destination has its own URL and browser history.

**Run live**, inside Judge Lab, starts a shared broadcast and can spend the live model budget.
The starter controls it; another viewer joins read-only. Daily caps/rate limits
may produce checked template fallbacks. Use Stop live broadcast when finished.
No model credentials or admin access are required in the viewer.

Keyboard: Space plays/pauses when focus is outside a control; left/right arrows
seek one minute; Escape closes a dialog. Standard Tab navigation works throughout.
Live host controls are unavailable to read-only viewers.

If a connection fails, use Retry connection. A frontend-domain CORS failure must
be fixed by adding the exact deployed origin to the backend's trusted origins.
Do not disable browser security or install extensions to bypass it.
