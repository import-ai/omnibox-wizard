# Task Description

Extract structured properties from the given text content, identifying key entities and concepts that appear in the document.

# Guidelines

- Extract specific entities mentioned in the text, not general categories
- For each property type, only include items that are explicitly mentioned or clearly referenced
- If no relevant entities are found for a property type, return an empty array
- Your response must be in JSON format with the specified property keys
- Extract entities in user's preference language when possible
- Prioritize accuracy and specificity

# Universal Properties (Always Extract)

- **main_topic**: The primary subject or theme of the document (1-2 items max)
- **key_concepts**: Important concepts, ideas, or themes discussed (3-5 items max)
- **persons**: Specific people mentioned by name
- **organizations**: Companies, government departments, schools, institutions mentioned
- **locations**: Countries, cities, landmarks, geographic places mentioned
- **products**: Specific product names or services mentioned (e.g. iPhone 16, ChatGPT-5)
- **technologies**: Professional technical terms mentioned (e.g. Large Language Models, Quantum Computing, Blockchain)
- **events**: Specific events mentioned (e.g. 2025 World AI Conference)

# Document-Specific Properties

## Meeting Notes (meeting_notes)
- **meeting_title**: Meeting subject/title
- **meeting_date**: Meeting date (ISO format)
- **attendees**: List of attendees
- **agenda_items**: Meeting agenda items
- **key_decisions**: Important decisions made
- **action_items**: Tasks with owner and due date [{"task": "...", "owner": "...", "due_date": "..."}]
- **unresolved_issues**: Issues that need follow-up
- **sentiment**: Meeting atmosphere ("Positive", "Neutral", "Controversial")

## Technical Design (technical_design)
- **project_name**: Project or system name
- **tech_stack**: Key technologies and frameworks used
- **architecture_type**: System architecture style
- **api_endpoints**: API definitions [{"method": "...", "path": "...", "description": "..."}]
- **database_schema**: Database tables [{"table": "...", "fields": [...]}]
- **dependencies**: External services/components
- **performance_targets**: Performance requirements
- **risks_and_mitigations**: Risks and solutions [{"risk": "...", "mitigation": "..."}]

## Market Analysis (market_analysis)
- **report_type**: Specific report type
- **target_market**: Target market or user group
- **analyzed_companies**: Companies analyzed
- **key_findings**: Core findings and conclusions
- **data_sources**: Referenced data sources
- **swot_analysis**: SWOT analysis {"strengths": [...], "weaknesses": [...], "opportunities": [...], "threats": [...]}
- **market_size**: Market size and growth data
- **future_trends**: Predicted market trends

## Legal Contract (legal_contract)
- **contract_type**: Type of contract
- **party_a**: First party full name
- **party_b**: Second party full name
- **effective_date**: Contract effective date
- **term**: Contract duration/term
- **governing_law**: Applicable law and jurisdiction
- **payment_terms**: Payment terms and amounts
- **liability_clause**: Liability limitation summary
- **confidentiality_period**: Confidentiality period

## Resume (resume)
- **candidate_name**: Candidate's name
- **contact_info**: Contact information {"email": "...", "phone": "..."}
- **education_history**: Education background [{"school": "...", "major": "...", "degree": "...", "period": "..."}]
- **work_experience**: Work history [{"company": "...", "position": "...", "period": "...", "summary": "..."}]
- **skills_set**: Skills list
- **years_of_experience**: Total work experience in years
- **current_location**: Current location
- **certifications**: Professional certifications

## User Interview (user_interview)
- **interviewee_profile**: User profile {"user_id": "...", "role": "...", "industry": "..."}
- **interview_date**: Interview date
- **user_goals**: User goals and objectives
- **pain_points**: User pain points and frustrations
- **key_quotes**: Important user quotes
- **feature_requests**: Requested features
- **overall_sentiment**: User's overall sentiment
- **researcher**: Interview researcher/conductor

## Project Proposal (project_proposal)
- **project_title**: Official project name
- **project_owner**: Project owner/sponsor
- **objectives**: Main project objectives
- **stakeholders**: Key stakeholders
- **timeline_milestones**: Key milestones [{"milestone": "...", "date": "..."}]
- **budget_estimate**: Estimated budget
- **deliverables**: Project deliverables
- **success_metrics**: Success metrics/KPIs

## Press Release (press_release)
- **announcement_subject**: Core announcement
- **company_involved**: Companies involved
- **key_persons**: Key people mentioned with titles
- **release_date**: Release date
- **financial_figures**: Key financial numbers
- **purpose_of_funds**: (For funding news) Fund usage
- **forward_looking_statements**: Future plans summary
- **media_contact**: Media contact info {"name": "...", "email": "..."}

## How-To Guide / SOP (how_to_guide)
- **procedure_title**: Guide or process title
- **target_audience**: Intended audience/readers
- **prerequisites**: Required conditions or preparations
- **steps**: Structured operation steps [{"step": 1, "action": "..."}]
- **expected_outcome**: Expected result after completion
- **troubleshooting**: Common issues and solutions [{"problem": "...", "solution": "..."}]
- **tools_required**: Required software/hardware tools
- **last_verified_date**: Last verified date (ISO format)

## Research Paper / Academic Article (research_paper)
- **paper_title**: Paper title
- **authors**: Author list with affiliations
- **publication_info**: Publication details {"journal": "...", "year": ...}
- **problem_statement**: Research problem being addressed
- **methodology**: Research method used
- **key_findings**: Most important results/conclusions
- **datasets_used**: Datasets used in experiments
- **limitations**: Acknowledged limitations or future improvements

## Financial Report (financial_report)
- **report_period**: Reporting period (e.g., "Q3 2024", "FY 2024")
- **company_name**: Reporting company
- **revenue_figures**: Key revenue numbers
- **profit_loss**: Profit/loss statements
- **key_metrics**: Important financial KPIs
- **segment_performance**: Performance by business segment
- **risk_factors**: Identified financial risks
- **outlook**: Future financial guidance
- **auditor**: External auditor information

## Marketing Campaign (marketing_campaign)
- **campaign_name**: Campaign title/name
- **campaign_period**: Campaign duration
- **target_demographics**: Target audience segments
- **marketing_channels**: Channels used (social media, email, etc.)
- **budget_allocation**: Budget breakdown by channel
- **key_messages**: Core marketing messages
- **success_metrics**: Campaign KPIs and goals
- **creative_assets**: Mentioned creative materials
- **campaign_manager**: Person responsible for campaign

## Product Specification (product_spec)
- **product_name**: Product name/title
- **version**: Product version number
- **feature_list**: Key features and capabilities
- **technical_requirements**: System/hardware requirements
- **user_stories**: User scenarios or use cases
- **acceptance_criteria**: Definition of done criteria
- **dependencies**: Required integrations or components
- **constraints**: Technical or business limitations
- **priority_level**: Development priority

## Customer Feedback (customer_feedback)
- **feedback_type**: Type of feedback (Complaint, Suggestion, Praise, etc.)
- **customer_info**: Customer details {"id": "...", "segment": "..."}
- **product_service**: Product/service being discussed
- **satisfaction_score**: Numerical ratings if mentioned
- **specific_issues**: Detailed problems or concerns
- **improvement_suggestions**: Customer suggestions
- **follow_up_required**: Whether follow-up is needed
- **feedback_channel**: How feedback was received

## Training Material (training_material)
- **course_title**: Training course or module name
- **target_learners**: Intended audience/learners
- **learning_objectives**: Educational goals
- **course_duration**: Expected time to complete
- **prerequisite_knowledge**: Required background knowledge
- **assessment_methods**: How learning is evaluated
- **certification_offered**: Available certifications
- **instructional_design**: Teaching methodology used
- **course_materials**: Required textbooks, software, etc.

## Incident Report (incident_report)
- **incident_title**: Incident summary
- **incident_date**: When incident occurred
- **severity_impact**: Impact level and affected users
- **root_cause**: Underlying cause of incident
- **timeline**: Key events timeline [{"time": "...", "event": "..."}]
- **resolution_steps**: Actions taken to resolve
- **lessons_learned**: Key takeaways
- **preventive_measures**: Steps to prevent recurrence
- **incident_commander**: Person who led response

## Survey Results (survey_results)
- **survey_title**: Survey name/topic
- **survey_period**: Data collection timeframe
- **sample_size**: Number of respondents
- **response_rate**: Participation rate percentage
- **key_demographics**: Respondent characteristics
- **major_findings**: Most important results
- **statistical_significance**: Confidence levels mentioned
- **methodology**: Data collection approach
- **recommendations**: Suggested actions based on results

## Policy Document (policy_document)
- **policy_title**: Official policy name
- **effective_date**: When policy takes effect
- **policy_owner**: Department/person responsible
- **scope_applicability**: Who/what policy applies to
- **key_requirements**: Main policy requirements
- **compliance_procedures**: How compliance is ensured
- **violations_consequences**: Penalties for non-compliance
- **review_schedule**: Policy review frequency
- **related_policies**: Connected or referenced policies

## Email Communication (email_communication)
- **email_subject**: Email subject line
- **sender**: Email sender information
- **recipients**: Primary recipients list
- **cc_bcc**: CC/BCC recipients if mentioned
- **email_type**: Type (announcement, request, update, etc.)
- **key_requests**: Specific asks or requests made
- **deadlines**: Mentioned deadlines or dates
- **attachments**: Referenced file attachments
- **follow_up_needed**: Whether response/action is required

## Job Description (job_description)
- **job_title**: Position title
- **department**: Department or team
- **employment_type**: Full-time, part-time, contract, etc.
- **location_type**: Remote, on-site, hybrid
- **experience_required**: Years of experience needed
- **key_responsibilities**: Main job duties
- **required_qualifications**: Must-have skills/education
- **preferred_qualifications**: Nice-to-have skills
- **compensation_range**: Salary range if mentioned
- **benefits_package**: Benefits offered

## Event Planning (event_planning)
- **event_name**: Event title
- **event_date**: Scheduled date and time
- **event_location**: Venue information
- **event_type**: Conference, workshop, social, etc.
- **expected_attendance**: Number of attendees
- **agenda_schedule**: Event schedule/program
- **speakers_presenters**: Featured speakers
- **budget_costs**: Event budget breakdown
- **logistics_requirements**: Equipment, catering, etc.
- **registration_process**: How people sign up

# Output Format

## Base Structure (Always Include)
```json
{
  "main_topic": ["topic1", "topic2"],
  "key_concepts": ["concept1", "concept2", "concept3"],
  "persons": ["person1", "person2"],
  "organizations": ["org1", "org2"],
  "locations": ["location1", "location2"],
  "products": ["product1", "product2"],
  "technologies": ["tech1", "tech2"],
  "events": ["event1", "event2"]
}
```

## Complete Output (Include document-specific properties when applicable)
```json
{
  // Universal properties (always include)
  "main_topic": ["topic1"],
  "key_concepts": ["concept1", "concept2"],
  "persons": ["person1"],
  "organizations": ["org1"],
  "locations": ["location1"],
  "products": ["product1"],
  "technologies": ["tech1"],
  "events": ["event1"],
  
  // Document-specific properties (include based on document type)
  "meeting_title": "...",        // for meeting_notes
  "project_name": "...",         // for technical_design
  "candidate_name": "...",       // for resume
  "contract_type": "...",        // for legal_contract
  // ... other document-specific properties as needed
}

# Meta info

- Current time: {{ now }}
- User's preference language: {{ lang }}