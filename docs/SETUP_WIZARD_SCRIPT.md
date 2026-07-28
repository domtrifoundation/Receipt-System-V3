# The First-Run Setup Wizard — Complete Interactive Script

This is the actual, word-for-word script for the normal-mode (`dev_mode: false`) first-run wizard — what a non-technical owner actually sees and reads, not the engineering description of how it works underneath. The technical mechanism for each step already exists in `v3-deepdive-11-setup-api.md` §7 and each system's own deep-dive; this document is the layman-facing script built on top of those mechanisms, kept consistent with them rather than duplicating their own technical detail.

**Writing rules followed throughout**: plain words over technical terms wherever a plain word says the same thing accurately. Every step explains *why* it's being asked, not just *what* to enter. Every optional step is visibly, unambiguously skippable — no dark patterns, no guilt-tripping copy. Concise: if a sentence can be cut without losing clarity, it's cut.

---

## Step 0: Welcome

```
Welcome. Let's get this set up — it takes a few minutes, and you can
change almost anything here later.

First, a quick question that decides what we'll ask you next:

  How will you be using this?

  [1] Just for myself
      → A simple, personal setup. Most of the questions below won't apply to you.

  [2] For my company or team
      → Multiple people will use this, but it stays private to your organization.

  [3] For the public — anyone can sign up
      → You're running this as a real service other people will use and trust
        with their own data. We'll walk through everything that involves,
        including a few things you'll want a lawyer's eyes on before you launch.
```

**What this decides, technically**: `tenancy_mode: single` for [1]; `tenancy_mode: multi` for [2] and [3]; `public_facing: true` only for [3] (or if the owner later enables Tunnel Exposure in [2], which flips this automatically). Every step below states which of the three branches it applies to.

---

## Step 1: Your own account

**Applies to: all three branches.**

```
Now let's set up your own account — you'll be the owner of this
installation.

How do you want to log in?

  [1] Sign in with Google
  [2] Use a passkey (fingerprint, face unlock, or a security key)
  [3] Get a login code by email
  [4] Get a login code by text message

We don't support passwords, on purpose — every option above is safer than
a password, and none of them can be guessed or leaked in a data breach the
way a password can.

You can add more of these later and use any of them to log in.
```

*(If [1] is chosen: redirect to Google, handle the callback, done. If [2]: run the passkey registration prompt the browser/OS provides. If [3] or [4]: send a code, ask for it back.)*

**[1] only**: `tenancy_mode: single` skips straight to Step 2 after this — a single-user install has nothing left in Step 1 to configure.

---

## Step 2: Run automatically when your computer starts

**Applies to: all three branches.**

```
Do you want this to start automatically when your computer turns on?

  [Yes, start automatically]   [No, I'll start it myself]

You can change this anytime later in Settings.
```

---

## Step 3: Making this reachable from outside your network

**Applies to: branch [2] and [3] only.** *(Skipped entirely for [1] — a personal install has no reason to be reachable from outside your own device.)*

```
Right now, this only works on your own network. If you want people
outside your building or home network to reach it — for example, your
team working remotely, or the public if you chose that earlier — we need
to open a secure path to the outside internet.

  [Set this up now]   [Skip — I'll only use this on my own network]
  [Skip — I'll set this up later in Settings]

If you're setting up for the public, you'll need this. If it's just your
team and everyone's always on the same office network, you can skip it.
```

*(If "Set this up now": walks through Cloudflare Tunnel setup — log in to a free Cloudflare account if the owner doesn't have one, pick a web address like `receipts.yourcompany.com`, confirm it's working. Full technical detail: `v3-deepdive-43-tunnel-exposure.md`.)*

```
One more thing: since this will be reachable by anyone with the address,
we're going to require a second login step (like a text message code, on
top of your regular login) for you and anyone else with admin access.
This is on by default and can't be turned off while this stays reachable
from outside — it's the one place we don't let you turn off a safety
feature, because it's not just your own data at risk once other people
are trusting you with theirs.
```

*(This message only appears if the owner picks "Set this up now" — it's the plain-language explanation of the automatic 2FA-floor behavior already designed in `v3-deepdive-05-auth-tenancy-api.md` §4.6.1.)*

---

## Step 4: Groups — if you're setting this up for a team

**Applies to: branch [2] only.** *(Branch [3] can also set this up later from Settings if it turns out to be relevant; not offered here since a public sign-up service's initial users aren't yet organized into any team.)*

```
Since you said this is for your company or team: do people on your team
need to see each other's receipts, or should everyone's stay private
even from each other?

  [Set up a shared team space]   [Keep everyone's data private, even from each other]
  [Not sure yet — I'll set this up later]

If you set up a shared space, you can add people to it and optionally
make someone a manager who can see the whole team's combined reports —
without giving them full admin access to everything else.
```

---

## Step 5: Getting paid — only if you want to charge for this

**Applies to: branch [2] and [3].** *(Skipped for [1] — there's no one to charge.)*

```
By default, everything here is free for everyone who uses it — you don't
need to touch this step at all unless you actually want to charge people.

Do you want to set up paid plans?

  [Set this up now]   [No — everything stays free]   [I'll decide later in Settings]
```

*(If "Set this up now": pick a payment processor — PayMongo is the default and simplest, Xendit is the alternative — enter the account credentials, then walk through the actual pricing/tier setup.)*

```
A couple more choices about how charges work:

If someone upgrades partway through their billing period, when should
they be charged?

  [Charge them right away, prorated for the days remaining]
  [Wait until their next billing period to charge the new price]
  [Let them use the upgrade free until the period after next — the most
   generous option, good if you want upgrading to feel risk-free]

If someone downgrades or cancels partway through, what happens to what
they already paid for the rest of that period?

  [Refund them right away, for the unused days]
  [Credit it toward their next bill instead of refunding]
  [No refund — they keep access until the period they already paid for ends]

You can set these two independently, and change either one anytime.
```

*(This is the actual proration policy from `v3-deepdive-22-billing-subscription-api.md` §3.3, in plain language. Note for whoever reviews this script before it ships: whichever choice the owner makes here should be reflected accurately in the real Terms of Service — see `docs/LEGAL_REVIEW_NEEDED.md` §V(I) and §VI(B) on refund/pricing terms belonging in that document.)*

---

## Step 6: Text message notifications

**Applies to: branch [2] and [3].** *(Skipped for [1] — a personal install has no one else to notify.)*

```
Want this to be able to text people (for example, "your files are
ready" or "you have a new flagged item to review")?

  [Set this up now]   [No, skip this]   [I'll set this up later in Settings]

If you're in the Philippines, we recommend Semaphore or PhilSMS — they're
built for Philippine phone numbers and cost less per message than
international options. Twilio is also available if you'd rather use it,
or if you have users outside the Philippines.
```

*(If "Set this up now": the owner picks one or more providers. For Semaphore/PhilSMS specifically, an extra real step appears:)*

```
One more thing for [Semaphore/PhilSMS]: Philippine phone carriers require
your texts to come from a registered sender name, or they'll often get
filtered out as spam before they even arrive. We'll walk you through
registering one now — it usually takes a few minutes.

  [Register a sender name now]   [I already have one — enter it]
```

---

## Step 7: Where receipts come in from

**Applies to: all three branches.**

```
How do you want to add receipts?

  [x] Upload directly (always available, nothing to set up)
  [ ] Take photos with your camera, right in the browser (always available)
  [ ] Watch a Google Drive folder — receipts you drop in there get
      processed automatically

If you want the Google Drive option, share your receipts folder with
this email address, the same way you'd share a folder with a coworker:

  [receipts-bot@yourinstall.iam.gserviceaccount.com]

  [I've shared the folder]   [Skip — I'll just upload directly]
```

---

## Step 8: Finding addresses on receipts

**Applies to: all three branches**, but framed differently depending on scale.

```
This system can double-check the addresses on your receipts against
real map data — useful for catching typos and confirming a receipt is
genuinely from where it says it's from.

  [Use the built-in free option]   [Skip this — I don't need address checking]

The built-in option works out of the box and is free for typical use.
If you're processing a very large number of receipts and expect to
outgrow the free tier, you can set up your own unlimited option later —
see Settings → Address Checking for a guide.
```

*(The "unlimited option later" reference points to `docs/SELF_HOSTED_NOMINATIM.md` — deliberately not offered as a first-run choice, since it's real infrastructure work not appropriate for a first-run wizard's own scope.)*

---

## Step 9: How powerful should the AI processing be?

**Applies to: all three branches.**

```
We looked at your computer's hardware and have a recommendation:

  Recommended for your hardware: [Balanced]

  [ ] Lightweight — fastest, uses the least resources, good for older
      or lower-powered hardware
  [x] Balanced — recommended for your hardware
  [ ] Maximum accuracy — slower, uses more resources, best results

You can change this anytime, and it won't affect receipts you've
already processed.
```

*(This is `scoring.py`'s own recommendation from `v3-deepdive-11-setup-api.md` §5.4, presented as three plain labels instead of raw hardware-tier jargon.)*

---

## Step 10: Terms of Service and Privacy Policy

**Applies to: branch [3] specifically; branches [1] and [2] see a shorter version.**

```
Before you finish setup, please review and accept our Terms of Service
and Privacy Policy:

  [Read Terms of Service]   [Read Privacy Policy]

  [ ] I have read and accept both

Since you're setting this up as a public service, we want to be
especially clear: you're responsible for having your own Terms of
Service and Privacy Policy reviewed by a lawyer before real people sign
up and trust you with their data. This isn't legal advice, and the
default documents that ship with this software are a starting point, not
a substitute for that review.
```

*(For branches [1] and [2], this step still appears — every install needs to accept whatever ToS applies to the software itself — but the "you're responsible for your own legal review" paragraph only appears for branch [3], since a personal or internal install isn't the scenario `docs/LEGAL_REVIEW_NEEDED.md` is actually about.)*

---

## Step 11: All set

```
That's everything. Setting things up now — this takes a moment.

[Progress bar / Boot Sequence screen]

Done! You're ready to go.
```

---

## A note on maintaining this script

Every step above is a plain-language front end to a real, already-designed technical mechanism cited inline. If any of those underlying mechanisms change, this script needs a matching update in the same pull request — the same "documentation updated in the same PR as the change it describes" discipline `docs/MAINTENANCE.md` §6 already requires for the technical deep-dives, applied here to the user-facing copy as well.
