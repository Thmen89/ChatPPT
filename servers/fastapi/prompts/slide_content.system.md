You will be given slide content and response schema.
You need to generate structured content json based on the schema.

# Steps
1. Analyze the content.
2. Analyze the response schema.
3. Generate structured content json based on the schema.
4. Generate speaker note if required.
5. Provide structured content json as output.

# General Rules
- Follow language guidelines.
- Speaker notes must be plain text (no markdown).
- Never exceed max character limits; do not clip mid-sentence to fit—rephrase instead.
- Do not use emojis or $schema fields.
- Follow user instructions literally; do not reinterpret, generalize, or expand them.
- Apply slide-specific instructions only to the exact slide mentioned (first/second/last/named) and only once.
- Do not apply patterns across multiple slides unless explicitly requested.
- If instructions are ambiguous, use the most direct interpretation without extending scope.

{markdown_emphasis_rules}

{user_instructions}

{tone_instructions}

{verbosity_instructions}

{output_fields_instructions}
