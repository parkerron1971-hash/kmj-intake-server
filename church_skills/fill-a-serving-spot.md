---
name: fill-a-serving-spot
use_when: a serving spot at a service is open or someone can't make it, and the person wants someone asked to take it (one person, the whole team, or every open spot in the coming weeks)
triggers: open spot, serving spot, fill the spot, fill a spot, fill that spot, fill sunday, fill the schedule, cover sunday, cover the spot, need someone to serve, need a volunteer, find a volunteer, find someone to serve, find someone to cover, who can serve, who could serve, who can cover, who could cover, ask someone to serve, short on volunteers, short a volunteer, can't make it sunday
actions: serving_spot, ask_to_serve, offer_serving_spot, take_back_serving_ask, fill_serving_spots
needs: serving_spots
---
STEPS
1. Look first with serving_spot for that service and place: who holds each spot (open, asked, said yes) and who on the team could take it, best first. With no place named, serving_spot with only the day shows what is open that day. A day with two services needs the time.
2. Suggest from that list only: say the first one or two names and why (trained for it, fewest Sundays this month). Never suggest someone the list says can't (away, already on another spot then, at their Sundays for the month), and never someone who isn't on the team.
3. Ask the person who to ask, and wait for their yes to that name and that spot. If they would rather not pick, offer the spot to the whole team instead (offer_serving_spot): the first yes takes it.
4. Once they say yes, send ask_to_serve with the day, time, place and person, exactly as they agreed. To fill every open spot over the coming weeks, use fill_serving_spots only when they ask for that.
5. If the result refuses (they are away, already on another spot, not on the team, every spot is taken), say what it says and suggest the next name from step 1. Nothing was asked.

HAND BACK
Say who was asked, for which spot and service, that it goes out on the next send, and that it is asked and waiting for their answer. Never say the spot is filled or that they said yes: only their own answer does that. If they want it undone before it goes out, take_back_serving_ask takes it back (a fill's asks with "fill": true).

NEVER
- Never ask anyone the person hasn't agreed to.
- Never take back someone's yes: that is a conversation first, then Who serves when.
