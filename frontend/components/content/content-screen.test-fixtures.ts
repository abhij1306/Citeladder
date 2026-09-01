/** A bounded stand-in for the server-owned skill catalog. */
function skill(
  id: string,
  label: string,
  description: string,
  structure: string,
  tone: string,
  lengthHint: string,
  channel = 'web',
) {
  return {
    id,
    label,
    channel,
    description,
    structure: [structure],
    tone,
    length_hint: lengthHint,
  };
}

export const contentSkillCatalogFixture = {
  version: 'content-skills-v4',
  default_skill_id: 'content_page',
  skills: [
    skill(
      'content_page',
      'Website content page',
      'A publish-ready page spec.',
      'The final H1.',
      'Clear and specific.',
      '500–800 words.',
    ),
    skill(
      'about_us',
      'About Us page',
      'A factual canonical company profile.',
      'An opening company and offering definition.',
      'Factual and specific.',
      '400–800 words.',
    ),
    skill(
      'article',
      'Article',
      'Authoritative long-form piece.',
      'A specific H1.',
      'Expert.',
      '900–1400 words.',
    ),
    skill(
      'blog',
      'Blog post',
      'Answer-first post with worked examples.',
      'H1 phrased as a search.',
      'Conversational.',
      '600–900 words.',
    ),
    skill(
      'linkedin',
      'LinkedIn post',
      'Professional post carrying one idea.',
      'An opening line.',
      'Professional.',
      '150–300 words.',
      'social',
    ),
  ],
};
