"""Reusable content skills (invariant 1: config lives here).

A *skill* is the reusable half of a content request: everything about the
FORMAT, STRUCTURE, LENGTH, and TONE of an output that does not depend on the
particular topic the user typed. The user's prompt supplies the subject; the
skill supplies the craft. Splitting them this way means a demand signal only
has to describe *what* to write about — the skill already knows what a
LinkedIn post or an FAQ page is supposed to look like.

Each definition renders to a deterministic directive string that
``message_builder`` prepends to the user's instruction. Rendering is pure and
ordered, so the same skill always produces byte-identical text and therefore a
stable ``message_digest`` for provenance.

Skill ids are persisted on ``ContentGeneration.skill_id``; never rename or
remove one without a migration for existing rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# Channel groups exist only to organise the picker; they are not persisted.
CHANNEL_WEB: Final = "web"
CHANNEL_SOCIAL: Final = "social"
CHANNEL_VIDEO: Final = "video"
CHANNEL_COMMUNITY: Final = "community"
CHANNEL_EMAIL: Final = "email"

CONTENT_CHANNELS: Final[tuple[str, ...]] = (
    CHANNEL_WEB,
    CHANNEL_SOCIAL,
    CHANNEL_VIDEO,
    CHANNEL_COMMUNITY,
    CHANNEL_EMAIL,
)


@dataclass(frozen=True)
class ContentSkillDefinition:
    """One reusable output format.

    ``directive`` is the lead instruction; ``structure`` is the ordered
    scaffold the model should follow; ``tone`` and ``length_hint`` constrain
    register and size. ``description`` is user-facing picker copy and is never
    sent to the model.
    """

    id: str
    label: str
    channel: str
    description: str
    directive: str
    structure: tuple[str, ...] = field(default_factory=tuple)
    tone: str = ""
    length_hint: str = ""
    #: Format-specific rules, appended to the evidence rules every skill gets.
    rules: tuple[str, ...] = field(default_factory=tuple)

    def render_directive(self) -> str:
        """Deterministic multi-part instruction prepended to the user prompt.

        The shared evidence rules are appended here rather than repeated in
        each definition, so no format can ship without them.
        """
        parts = [self.directive]
        if self.structure:
            scaffold = "\n".join(
                f"{index}. {step}" for index, step in enumerate(self.structure, start=1)
            )
            parts.append(f"Follow this structure:\n{scaffold}")
        if self.tone:
            parts.append(f"Tone: {self.tone}")
        if self.length_hint:
            parts.append(f"Length: {self.length_hint}")
        constraints = "\n".join(f"- {rule}" for rule in (*_EVIDENCE_RULES, *self.rules))
        parts.append(f"Rules:\n{constraints}")
        return "\n\n".join(parts)


# Sourcing rules shared by every format. Content that will be published under
# the customer's own domain cannot invent pricing, statistics, or capabilities,
# and an unknown must read as unknown rather than be smoothed over.
_EVIDENCE_RULES: Final[tuple[str, ...]] = (
    "Never invent facts, pricing, capabilities, statistics, quotes, or examples. "
    "Everything factual must trace to the grounding envelope.",
    "Where the evidence does not support a claim, say the information is not "
    "available rather than filling the gap.",
    "Keep the exact qualifiers the evidence uses — do not restate an estimate "
    "as a certainty.",
)


_DEFINITIONS: Final[tuple[ContentSkillDefinition, ...]] = (
    ContentSkillDefinition(
        id="content_page",
        label="Website content page",
        channel=CHANNEL_WEB,
        description=(
            "A publish-ready page spec: meta block, sections, CTA, and sources."
        ),
        directive=(
            "Build a website content page — a comparison guide, listicle, "
            "how-to, or pillar page. Produce a page-ready build spec, not a "
            "research report: everything you write is copy intended to render "
            "on the page. Prefer structured tables and lists over repeated "
            "prose, and include only copy that earns its space."
        ),
        structure=(
            "The final H1, as a level-1 Markdown heading.",
            "A `## Meta` section listing, as a bullet each: Target query; "
            "Audience and intent; Meta title (60 characters or fewer); Meta "
            "description (155 characters or fewer); Canonical route; Primary "
            "CTA and its destination.",
            "A `## Sections` block with one `###` heading per page section, "
            "each holding final page-ready copy.",
            "Structured comparison tables, step lists, or item data wherever "
            "they carry the information better than prose.",
            "A one-line imagery note under any section whose subject calls "
            "for a visual, so the page is not an unbroken wall of text.",
            "A closing `## Sources` section listing each source used and the "
            "claims it supports.",
        ),
        tone="Clear and specific; informative rather than promotional.",
        length_hint=(
            "500–800 words for a simple content page, 800–1500 for a "
            "comparison or listicle (50–100 words per item), 1200–2000 for an "
            "in-depth guide. Treat these as budgets, not quotas."
        ),
        rules=(
            "Use exactly one H1 and a logical H2/H3 hierarchy beneath it.",
            "For a comparison or listicle, give every item the same shape: "
            "what it is, who it is best for, the key verified fact, then two "
            "or three sentences on decision-relevant strengths and limits.",
            "Do not include research methodology, exhaustive feature "
            "inventories, or prose that merely restates a table.",
        ),
    ),
    ContentSkillDefinition(
        id="article",
        label="Article",
        channel=CHANNEL_WEB,
        description="Authoritative long-form piece for search and citation.",
        directive=(
            "Write an authoritative, evidence-led article. Lead with the "
            "substantive answer rather than background. Every factual claim "
            "must trace to the grounding envelope; where evidence is absent, "
            "write around the gap instead of estimating."
        ),
        structure=(
            "A specific H1 that states the subject, not a teaser.",
            "An opening paragraph that answers the core question directly.",
            "H2 sections, each covering one distinct sub-question.",
            "Concrete specifics — numbers, named entities, procedures — over "
            "adjectives.",
            "A short closing section on what the reader should do next.",
        ),
        tone="Expert, plain, and free of marketing superlatives.",
        length_hint="900–1400 words.",
    ),
    ContentSkillDefinition(
        id="blog",
        label="Blog post",
        channel=CHANNEL_WEB,
        description="Answer-first post with practical, worked examples.",
        directive=(
            "Write an answer-first blog post. Give the reader the takeaway in "
            "the first 50 words, then earn it with practical detail and at "
            "least one worked example."
        ),
        structure=(
            "H1 phrased the way a reader would search for it.",
            "A two-to-three sentence direct answer up front.",
            "H2 sections that go deeper, each opening with its own key point.",
            "At least one concrete worked example or scenario.",
            "A brief summary of the main points.",
        ),
        tone="Conversational but precise; second person.",
        length_hint="600–900 words.",
    ),
    ContentSkillDefinition(
        id="faq",
        label="FAQ page",
        channel=CHANNEL_WEB,
        description="Question-and-answer page built to be quoted by AI answers.",
        directive=(
            "Write an FAQ page. Each question must be phrased exactly as a "
            "real person would ask it, and each answer must stand alone — "
            "quotable without the surrounding page for context."
        ),
        structure=(
            "A one-paragraph intro naming the topic the FAQ covers.",
            "H2 per question, written in natural question form.",
            "A self-contained 40–80 word answer under each question, "
            "leading with the direct answer before any qualification.",
            "Group related questions so the order reads logically.",
        ),
        tone="Neutral and factual; no persuasion.",
        length_hint="8–12 question/answer pairs.",
    ),
    ContentSkillDefinition(
        id="comparison",
        label="Comparison page",
        channel=CHANNEL_WEB,
        description="Balanced side-by-side evaluation with an explicit verdict.",
        directive=(
            "Write a comparison page. Be genuinely balanced: name the cases "
            "where each option is the weaker choice. State the criteria "
            "before applying them, and never compare on an attribute the "
            "grounding envelope does not support."
        ),
        structure=(
            "H1 naming the options being compared.",
            "A short verdict paragraph stating who should pick what.",
            "The comparison criteria, stated explicitly before use.",
            "A Markdown table scoring each option against each criterion.",
            "An H2 per option covering its strongest and weakest cases.",
            "A closing section on how to choose.",
        ),
        tone="Even-handed and specific; no vendor cheerleading.",
        length_hint="800–1200 words.",
    ),
    ContentSkillDefinition(
        id="youtube",
        label="YouTube script",
        channel=CHANNEL_VIDEO,
        description="Spoken-word video script with a hook and timed sections.",
        directive=(
            "Write a YouTube video script as spoken words, not prose to be "
            "read. Open with a hook that earns the first 15 seconds without "
            "clickbait, and write sentences a person can say in one breath."
        ),
        structure=(
            "A 2–3 sentence hook establishing the payoff.",
            "A one-line statement of what the video will cover.",
            "Timestamped sections, each with a spoken-word body.",
            "Suggested B-roll or on-screen text in [brackets].",
            "A closing call to action.",
        ),
        tone="Direct and energetic; spoken register, short sentences.",
        length_hint="900–1200 spoken words (roughly 6–8 minutes).",
        rules=(
            "Also supply a title under 60 characters and a description whose "
            "first two lines work as the above-the-fold summary.",
            "Write for the ear: no bullet syntax, tables, or Markdown "
            "formatting inside the spoken lines.",
        ),
    ),
    ContentSkillDefinition(
        id="tiktok",
        label="TikTok / Shorts",
        channel=CHANNEL_VIDEO,
        description="Short vertical video script with a three-second hook.",
        directive=(
            "Write a short vertical video script. The first line must land "
            "the hook in under three seconds. Every sentence has to justify "
            "the next one; cut anything that reads as preamble."
        ),
        structure=(
            "A hook line of at most 12 words.",
            "Three to five rapid beats, one idea each.",
            "On-screen text suggestions in [brackets].",
            "A closing line that prompts a comment or follow.",
        ),
        tone="Punchy, casual, first person; no corporate register.",
        length_hint="120–200 spoken words (under 60 seconds).",
        rules=(
            "Write for a vertical, sound-on-optional format: every spoken "
            "point needs an on-screen text equivalent.",
            "No Markdown in the spoken lines.",
        ),
    ),
    ContentSkillDefinition(
        id="reddit",
        label="Reddit post",
        channel=CHANNEL_COMMUNITY,
        description="Conversational community post with no promotional tone.",
        directive=(
            "Write a useful, conversational Reddit post. No promotional hype, "
            "no marketing voice, no calls to action — Reddit punishes all "
            "three. Share the specific experience or finding and let it "
            "stand on its own."
        ),
        structure=(
            "A plain, literal title with no clickbait.",
            "Context on why you are posting, in one short paragraph.",
            "The substance — specifics, numbers, what actually happened.",
            "An honest note on limitations or what you are unsure about.",
            "A genuine question inviting the community's experience.",
        ),
        tone="Peer to peer, first person, plainly self-aware.",
        length_hint="250–450 words.",
        rules=(
            "Name a plausible subreddit for the post and write to that "
            "audience's norms.",
            "Never link to the brand's own site or name it as a recommendation "
            "— self-promotion is what gets these posts removed.",
        ),
    ),
    ContentSkillDefinition(
        id="linkedin",
        label="LinkedIn post",
        channel=CHANNEL_SOCIAL,
        description="Professional post with a strong opening line and one idea.",
        directive=(
            "Write a LinkedIn post carrying exactly one idea. The first line "
            "shows above the fold and decides whether anyone reads the rest. "
            "Avoid the genre clichés: no fake-humble story framing, no "
            "one-word-per-line staircase, no 'Agree?' sign-off."
        ),
        structure=(
            "An opening line that states the idea or the tension.",
            "Two to four short paragraphs developing it with specifics.",
            "A concrete takeaway the reader can act on.",
            "Three to five relevant hashtags on the final line.",
        ),
        tone="Professional and direct; confident without self-congratulation.",
        length_hint="150–300 words.",
        rules=(
            "Only the first ~200 characters show before 'see more' — the idea "
            "must land inside them.",
            "Plain text only: LinkedIn renders no Markdown, so use line breaks "
            "rather than headings, bold, or bullet syntax.",
        ),
    ),
    ContentSkillDefinition(
        id="x",
        label="X / Twitter thread",
        channel=CHANNEL_SOCIAL,
        description="Threaded posts, each standing alone under 280 characters.",
        directive=(
            "Write an X thread. Every post must be under 280 characters and "
            "readable on its own, since posts get quoted out of context. "
            "Number them and put the strongest claim first, not last."
        ),
        structure=(
            "Post 1: the claim or result, complete in itself.",
            "Posts 2–N: one supporting point each, with specifics.",
            "A final post summarising the takeaway.",
        ),
        tone="Terse and declarative; no thread-bait or emoji bullets.",
        length_hint="5–9 posts, each under 280 characters.",
        rules=(
            "Count characters per post and stay under 280 including spaces.",
            "Put any link in the final post — links in the opening post "
            "suppress reach.",
        ),
    ),
    ContentSkillDefinition(
        id="instagram",
        label="Instagram caption",
        channel=CHANNEL_SOCIAL,
        description="Visual-first caption with a scannable body and hashtags.",
        directive=(
            "Write an Instagram caption that complements a visual rather than "
            "describing it. Front-load the hook — the caption truncates after "
            "roughly 125 characters."
        ),
        structure=(
            "A hook line under 125 characters.",
            "A short scannable body, line-broken for readability.",
            "A prompt to comment or save.",
            "Five to ten hashtags, grouped at the end.",
        ),
        tone="Warm and human; light, never breathless.",
        length_hint="100–200 words.",
        rules=(
            "Captions are not clickable — never write 'link below' or point at "
            "a URL; direct readers to the profile link instead.",
            "Plain text only: Instagram renders no Markdown.",
        ),
    ),
    ContentSkillDefinition(
        id="newsletter",
        label="Newsletter",
        channel=CHANNEL_EMAIL,
        description="Email issue with a subject line and a single clear payoff.",
        directive=(
            "Write a newsletter issue. Open with a subject line and preview "
            "text, then deliver one clear payoff — a reader should finish "
            "knowing exactly what changed and why it matters to them."
        ),
        structure=(
            "Subject line under 60 characters.",
            "Preview text under 100 characters that adds to the subject "
            "rather than repeating it.",
            "A greeting and a one-paragraph statement of the payoff.",
            "Two to four short sections with subheadings.",
            "A single, specific call to action.",
        ),
        tone="Familiar and direct, as if writing to one named reader.",
        length_hint="400–700 words.",
        rules=(
            "Assume an email client with limited formatting: short paragraphs, "
            "no deep heading hierarchy, no tables.",
            "Exactly one call to action — competing asks reduce clicks on all of them.",
        ),
    ),
)

CONTENT_SKILL_REGISTRY: Final[dict[str, ContentSkillDefinition]] = {
    definition.id: definition for definition in _DEFINITIONS
}

# Ordered ids for pickers and docs (registry insertion order is the UI order).
CONTENT_SKILL_IDS: Final[tuple[str, ...]] = tuple(CONTENT_SKILL_REGISTRY)
CONTENT_SKILLS: Final[frozenset[str]] = frozenset(CONTENT_SKILL_IDS)
# The website content page is the default selection: the product's one output
# type is `website_page`, so an unqualified request means a page.
CONTENT_DEFAULT_SKILL: Final = "content_page"

# Bumped whenever any directive text changes, so a generation's provenance
# records which catalog wrote it.
CONTENT_SKILL_CATALOG_VERSION: Final = "content-skills-v2"

# Back-compatible flat view: ``{skill_id: rendered directive}``.
CONTENT_SKILL_DIRECTIVES: Final[dict[str, str]] = {
    skill_id: definition.render_directive()
    for skill_id, definition in CONTENT_SKILL_REGISTRY.items()
}


def skill_directive(skill_id: str | None) -> str:
    """Rendered directive for ``skill_id``, falling back to the default skill."""
    definition = CONTENT_SKILL_REGISTRY.get(
        skill_id or CONTENT_DEFAULT_SKILL,
        CONTENT_SKILL_REGISTRY[CONTENT_DEFAULT_SKILL],
    )
    return definition.render_directive()
