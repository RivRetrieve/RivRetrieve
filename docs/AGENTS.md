# Documentation language guidelines

Apply these guidelines to documentation in `docs/` and its subdirectories.

## Audience

Write for an educated reader in hydrology who has basic Python knowledge.
Assume familiarity with established hydrological terms. Do not assume
software-engineering expertise or knowledge of RivRetrieve's internals.
Explain unfamiliar software concepts and project-specific terms where they
first matter.

## Clarity over compression

- Choose wording that makes the meaning easiest to understand.
- Prefer a slightly longer explanation when it makes a relationship, reason,
  or consequence clearer. Brevity is useful only when it preserves clarity.
- Keep useful, precise technical terms. Explain unfamiliar terms in plain
  language rather than replacing them with vague wording.
- Remove repetition, filler, and unnecessary detail. Each sentence should add
  a fact, definition, reason, example, qualification, consequence, or necessary
  connection.

## Sentences and terminology

- Prefer focused sentences and paragraphs. Let the explanation determine their
  length, and keep related qualifications close to the claims they qualify.
- Make actors, actions, conditions, and relationships explicit. Keep the words
  needed to make a sentence unambiguous.
- Prefer concrete verbs over abstract noun phrases: `compare` rather than
  `perform a comparison`.
- Unpack dense noun clusters into phrases that show how the concepts relate.
- Use consistent names for the same concept. Do not rotate technical synonyms
  for stylistic variety.
- Use active voice when it makes responsibility clearer. Passive voice is
  appropriate when the actor is unknown or irrelevant.
- Avoid em dashes. Use a sentence break, a comma, parentheses, or an explicit
  connecting word as appropriate.
- Avoid contrastive negation as a rhetorical device, such as `not merely X,
  but Y`. State the substantive point directly. Keep factual negatives and
  explicit distinctions when they explain a real limitation or prevent a
  likely misunderstanding.

## Voice

- Retain a factual, explanatory voice. Use direct instructions where
  appropriate, without requiring direct address to the reader.
- Keep the tone approachable through clear explanations and concrete examples.
  Avoid forced friendliness and conversational filler.
- Avoid promotional language, inflated claims, and unsupported praise. Explain
  the actual capability, behaviour, or result.
- Start with substance. Omit sentences that only announce what a section will
  explain or label a point as important.
- Use connectors when they express a real relationship, such as cause,
  consequence, or a condition. Remove decorative transitions.

## Explanations and examples

- Introduce a concept through its purpose and practical meaning before
  describing internal machinery.
- Explain what an operation does, what it returns, and the conditions needed
  to interpret the result.
- Use examples when they make an abstract distinction concrete. Explain what
  the example demonstrates and what the reader should notice in its output.
- Give examples enough context to understand the inputs and prerequisites.
  Keep code readable and preserve exact API names, identifiers, and values.
- Show output in code comments when it helps explain the result or tells the
  reader what to expect. Use accurate output for the example shown.
- Give code snippets breathing room. Separate logical steps with blank lines,
  and leave a blank line after an output comment block before the next step.
  Avoid stacking all statements into one uninterrupted block.
- Use numbered lists for sequences, bullets for sets, and tables for genuine
  comparisons or repeated fields. Keep connected reasoning in prose.
- Maintainer pages may contain necessary implementation detail. Explain
  project-specific concepts before relying on them.

## Precision and scope

- Preserve qualifications, uncertainty, units, source terminology, and
  distinctions that affect interpretation. Simplifying prose must preserve
  the meaning and strength of a claim.
- Describe current behaviour in ordinary documentation. Keep historical
  evidence explicitly historical.
- Keep null values, absent rows, and failed requests distinct. Preserve
  unknown source facts rather than supplying an explanation the evidence
  does not establish.
- Apply these principles without claiming formal ASD-STE100 compliance. They
  draw on plain-language and Simplified Technical English principles for
  human-readable documentation.
