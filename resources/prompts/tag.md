# Task Description

Generate 1-3 broad tags categorizing the main themes of the given text, along with 1-3 more specific subtopic tags.

# Guidelines

- Start with high-level domains (e.g. Science, Technology, Philosophy, Arts, Politics, Business, Health, Sports, Entertainment, Education)
- Consider including relevant subfields/subdomains if they are strongly represented throughout the conversation
- If content is too short (less than 10 tokens) or too diverse, use only ["General"]
- Your response must be in JSON format, with key "tags"
- Your tags should be in user's preference language
- Prioritize accuracy over specificity

# Output

```json
{"tags":["tag1","tag2","tag3"]}
```

# Meta info

- Current time: {{ now }}
- User's preference language: {{ lang }}