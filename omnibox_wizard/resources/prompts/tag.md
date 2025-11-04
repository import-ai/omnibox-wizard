# Task Description

Generate 1-3 broad tags categorizing the main themes of the given text, along with 1-3 more specific subtopic tags.

# Guidelines

- Start with high-level domains (e.g. Science, Technology, Philosophy, Arts, Politics, Business, Health, Sports, Entertainment, Education)
- Consider including relevant subfields/subdomains if they are strongly represented throughout the conversation
- If content is too short (less than 10 tokens) or too diverse, use only ["General"]
- **IMPORTANT: All tags MUST be in the user's preference language ({{ lang }})**
- Your response must be in JSON format, with key "tags"
- Prioritize accuracy over specificity

# Output Format
```json
{"tags":["tag1","tag2","tag3"]}
```

# Examples

**Example 1 (简体中文):**
Input: "讨论了机器学习算法和神经网络的应用"
Output: `{"tags":["技术","人工智能","机器学习"]}`

**Example 2 (English):**
Input: "Discussion about machine learning algorithms and neural networks"
Output: `{"tags":["Technology","Artificial Intelligence","Machine Learning"]}`

# Meta info

- Current time: {{ now }}
- **User's preference language: {{ lang }}**