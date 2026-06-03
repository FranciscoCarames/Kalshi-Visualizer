# What's Next (for the Project Brief)

> Plain-English blurb to paste into the Google Doc Project Brief. The Drive connector is read-only, so
> this cannot be written to the Doc automatically — paste it in manually.

The next round of work makes the tool faster to scan and harder to miss. First we clean up the dashboard
itself: a timezone selector (defaulting to Lisbon time) so every time reads correctly, an always-visible
strip showing how fresh the data is and how much was loaded, and a tidier layout that moves debug and raw
diagnostics out of the way unless you ask for them. Then we add a single, always-on table that scans
every loaded market across all the supported sports at once and ranks the best opportunities top to
bottom — replacing the old ranking chart with something you can actually sort. Behind the scenes we begin
saving snapshots over time, so the tool can flag clearly when a new opportunity appears or when a
previously blocked one changes, and can show a short list of what was recently worth watching. Finally we
improve the export options so the data is easy to pull out for analysis. For now the tool still focuses on
gross edge (before fees) and stays read-only and single-user; a move to a more modern web stack is planned
for the coming months.
