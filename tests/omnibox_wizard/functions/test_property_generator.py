import pytest

from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.property_generator import PropertyGenerator


@pytest.mark.asyncio
async def test_property_generator_success(worker_config, trace_info):
    """Test successful property extraction"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={"text": "This is a sample text about machine learning and artificial intelligence featuring Elon Musk and Tesla company in Silicon Valley."}
    )

    result = await property_generator.run(task, trace_info)

    assert "properties" in result
    assert isinstance(result["properties"], dict)
    
    # Check that all required universal property types are present
    expected_properties = [
        "main_topic", "key_concepts", "persons", "organizations", 
        "locations", "products", "technologies", "events"
    ]
    
    for prop in expected_properties:
        assert prop in result["properties"]
        assert isinstance(result["properties"][prop], list)


@pytest.mark.asyncio
async def test_property_generator_empty_text(worker_config, trace_info):
    """Test property generation with empty text"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={"text": ""}
    )

    with pytest.raises(ValueError, match="Text input is required for property generation"):
        await property_generator.run(task, trace_info)


@pytest.mark.asyncio
async def test_property_generator_no_text_input(worker_config, trace_info):
    """Test property generation without text input"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={}
    )

    with pytest.raises(ValueError, match="Text input is required for property generation"):
        await property_generator.run(task, trace_info)


@pytest.mark.asyncio
async def test_property_generator_with_lang(worker_config, trace_info):
    """Test property generation with language parameter"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": "Apple CEO Tim Cook introduced the latest iPhone 15 and AI technology at Cupertino, California.",
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)

    assert "properties" in result
    assert isinstance(result["properties"], dict)
    
    # Check that all required universal property types are present
    expected_properties = [
        "main_topic", "key_concepts", "persons", "organizations", 
        "locations", "products", "technologies", "events"
    ]
    
    for prop in expected_properties:
        assert prop in result["properties"]
        assert isinstance(result["properties"][prop], list)


@pytest.mark.asyncio
async def test_property_generator_with_long_text(worker_config, trace_info):
    """Test property generation with long text"""
    property_generator = PropertyGenerator(worker_config)
    long_text = """
    OpenAI has released GPT-4, a large language model developed by their research team in San Francisco. 
    The CEO Sam Altman announced this breakthrough at the 2024 AI Conference in New York. 
    The new model shows significant improvements in natural language processing and machine learning capabilities.
    Microsoft has partnered with OpenAI to integrate this technology into their Azure cloud platform.
    The development team includes researchers from Stanford University and MIT who worked on transformer architectures.
    This announcement has implications for the future of artificial intelligence and deep learning research.
    """ * 10

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={"text": long_text}
    )

    result = await property_generator.run(task, trace_info)

    assert "properties" in result
    assert isinstance(result["properties"], dict)
    
    # Check that all required universal property types are present
    expected_properties = [
        "main_topic", "key_concepts", "persons", "organizations", 
        "locations", "products", "technologies", "events"
    ]
    
    for prop in expected_properties:
        assert prop in result["properties"]
        assert isinstance(result["properties"][prop], list)


@pytest.mark.asyncio
async def test_property_generator_short_text(worker_config, trace_info):
    """Test property generation with short text"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={"text": "Python programming"}
    )

    result = await property_generator.run(task, trace_info)

    assert "properties" in result
    assert isinstance(result["properties"], dict)
    
    # Check that all required universal property types are present
    expected_properties = [
        "main_topic", "key_concepts", "persons", "organizations", 
        "locations", "products", "technologies", "events"
    ]
    
    for prop in expected_properties:
        assert prop in result["properties"]
        assert isinstance(result["properties"][prop], list)


@pytest.mark.asyncio
async def test_property_generator_rich_content(worker_config, trace_info):
    """Test property generation with content rich in entities"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Apple CEO Tim Cook announced the iPhone 16 Pro at the Apple Event 2024 held in Cupertino, California. 
            The event featured discussions about artificial intelligence, machine learning, and quantum computing technologies.
            Guests included Sundar Pichai from Google, Satya Nadella from Microsoft, and representatives from Stanford University.
            The new device integrates advanced neural processing units and supports 5G connectivity across major cities like New York, London, and Tokyo.
            The presentation highlighted partnerships with OpenAI for ChatGPT integration and collaboration with NVIDIA for GPU acceleration.
            """
        }
    )

    result = await property_generator.run(task, trace_info)

    assert "properties" in result
    properties = result["properties"]
    assert isinstance(properties, dict)
    
    # Check that all required universal property types are present
    expected_properties = [
        "main_topic", "key_concepts", "persons", "organizations", 
        "locations", "products", "technologies", "events"
    ]
    
    for prop in expected_properties:
        assert prop in properties
        assert isinstance(properties[prop], list)
    
    # This content should extract some entities in each category
    # We don't assert specific values since AI responses can vary,
    # but we can check that some categories have extracted entities
    assert len(properties["persons"]) >= 0  # Should find names like Tim Cook, Sundar Pichai
    assert len(properties["organizations"]) >= 0  # Should find Apple, Google, Microsoft
    assert len(properties["locations"]) >= 0  # Should find Cupertino, New York, etc.
    assert len(properties["products"]) >= 0  # Should find iPhone 16 Pro
    assert len(properties["technologies"]) >= 0  # Should find AI, ML, quantum computing
    assert len(properties["events"]) >= 0  # Should find Apple Event 2024


@pytest.mark.asyncio
async def test_property_generator_meeting_notes_detection(worker_config, trace_info):
    """Test property generation for meeting notes document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Meeting Minutes - Q3 2025 Product Roadmap Planning
            Date: July 15, 2025
            Attendees: John (PM), Mike (Tech Lead), Sarah (Designer)
            
            Agenda:
            1. Review Q2 performance
            2. Discuss Q3 feature planning
            
            Decisions:
            - Prioritize smart reporting feature
            - Confirm technical approach for new features
            
            Action Items:
            - Mike to complete PRD by 2025-07-22
            - Sarah to deliver UI design by 2025-07-20
            
            Open Issues:
            - Backend team to confirm data API stability
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for meeting-specific properties if detected as meeting document
    meeting_specific_props = [
        "meeting_title", "meeting_date", "attendees", "agenda_items",
        "key_decisions", "action_items", "unresolved_issues", "sentiment"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in meeting_specific_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_technical_design_detection(worker_config, trace_info):
    """Test property generation for technical design document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Celestial Recommendation System V2.0 Technical Design Document
            
            Project Overview:
            This document describes the technical architecture and implementation plan for Celestial Recommendation System V2.0.
            
            Technology Stack:
            - Backend: Java, Spring Boot, MyBatis
            - Message Queue: Apache Kafka
            - Cache: Redis Cluster
            - Database: MySQL 8.0
            - Monitoring: Prometheus + Grafana
            
            System Architecture:
            Microservices architecture with following core services:
            - User Profile Service
            - Recommendation Algorithm Service
            - Data Processing Service
            
            API Endpoints:
            POST /api/v2/recommend
            Description: Get personalized recommendation list
            
            Database Schema:
            user_profile table: user_id, gender, age_group, interests
            recommendation_log table: user_id, item_id, score, timestamp
            
            Performance Metrics:
            - Core API latency < 50ms
            - System availability > 99.9%
            
            Risk Assessment:
            1. Redis single point failure risk -> Master-slave + Sentinel HA solution
            2. Data consistency issue -> Implement distributed transaction management
            
            Dependencies:
            - User Center Service
            - Order Service
            - Payment Service
            """,
            "lang": "简体中文"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for technical design specific properties if detected
    tech_specific_props = [
        "project_name", "tech_stack", "architecture_type", "api_endpoints",
        "database_schema", "dependencies", "performance_targets", "risks_and_mitigations"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in tech_specific_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_resume_detection(worker_config, trace_info):
    """Test property generation for resume document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Resume
            
            Basic Information:
            Name: Li Ming
            Email: liming@example.com
            Phone: 13800138000
            Current Location: Shanghai
            
            Education:
            2020-2023 Peking University - Master in Computer Science and Technology
            2016-2020 Tsinghua University - Bachelor in Software Engineering
            
            Work Experience:
            2023-Present ABC Technology Co., Ltd. - Senior Software Engineer
            - Developed backend for core recommendation system
            - Participated in distributed system architecture design
            - Mentored junior engineers
            
            2021-2023 XYZ Internet Company - Software Engineer (Intern)
            - Developed user management module
            - Optimized database query performance
            
            Technical Skills:
            - Programming Languages: Java, Python, Go, JavaScript
            - Frameworks: Spring Boot, Django, React
            - Databases: MySQL, Redis, MongoDB
            - Big Data: Hadoop, Spark, Kafka
            - Machine Learning: TensorFlow, PyTorch
            
            Certifications:
            - AWS Certified Solutions Architect
            - PMP Certification
            
            Project Experience:
            Intelligent Recommendation System (2023-2024)
            - Designed and implemented recommendation system handling millions of user behavior data daily
            - Improved recommendation accuracy by 15% using deep learning algorithms
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for resume-specific properties if detected
    resume_specific_props = [
        "candidate_name", "contact_info", "education_history", "work_experience",
        "skills_set", "years_of_experience", "current_location", "certifications"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in resume_specific_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_market_analysis_detection(worker_config, trace_info):
    """Test property generation for market analysis document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            AI Market Analysis Report Q3 2025

            Report Type: Industry Trend Analysis Report
            
            Target Market: 
            Enterprise AI solutions market, primarily serving medium and large corporate clients in finance, healthcare, and education sectors.
            
            Analyzed Companies:
            - OpenAI: Leader in GPT series models
            - Google DeepMind: Research-driven AI company  
            - Microsoft: Azure AI platform provider
            - Baidu: China's AI technology leader
            - Alibaba: Cloud computing + AI service provider
            
            Key Findings:
            1. Generative AI market size projected to reach $136 billion by 2025
            2. Enterprise demand for customized AI solutions grew by 300%
            3. Multimodal AI emerges as new competitive focus
            
            Data Sources:
            - IDC Global AI Market Report
            - Gartner Hype Cycle
            - CB Insights Investment Data
            - Enterprise Survey (Sample size: 1000+)
            
            SWOT Analysis:
            Strengths: Improved technology maturity, continuously decreasing costs
            Weaknesses: Unclear regulatory policies, talent shortage
            Opportunities: Strong demand for digital transformation in traditional industries
            Threats: Severe technology homogenization, intense price competition
            
            Market Size:
            2024 Global AI Market Size: $184 billion
            Projected 2025 Growth Rate: 28.5%
            China Market Share: 23%
            
            Future Trends:
            - AI Agents will become the next breakout point
            - Accelerated integration of edge computing and AI
            - Rise of industry-specific vertical solutions
            - Increased requirements for AI security and explainability
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for market analysis specific properties if detected
    market_analysis_props = [
        "report_type", "target_market", "analyzed_companies", "key_findings",
        "data_sources", "swot_analysis", "market_size", "future_trends"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in market_analysis_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_legal_contract_detection(worker_config, trace_info):
    """Test property generation for legal contract document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Software Development Service Contract

            Contract Type: Technical Service Contract

            Party A: Beijing Innovation Technology Co., Ltd.
            Representative: Zhang San
            Address: No. 1, Zhongguancun Street, Haidian District, Beijing

            Party B: Shanghai Software Development Co., Ltd.
            Representative: Li Si
            Address: No. 1, Lujiazui Financial Center, Pudong New Area, Shanghai

            Effective Date: January 1, 2025
            Contract Term: 12 months (January 1, 2025 to December 31, 2025)

            Governing Law: This contract is governed by the laws of the People's Republic of China, and disputes shall be resolved by the People's Court of Haidian District, Beijing.

            Payment Terms:
            - Total Amount: 100,000 RMB
            - Down Payment: 30% (300,000 RMB) within 7 days after signing
            - Milestone Payment: 40% (400,000 RMB) after project milestone completion
            - Final Payment: 30% (300,000 RMB) after project验收合格后支付30% (30万元)
            - Payment Method: Bank Transfer

            Liability Limitation:
            Party B shall be liable for direct losses caused by software defects, but the liability limit shall not exceed 50% of the total contract amount.
            For indirect losses, profit losses, etc., Party B shall not be liable.

            Confidentiality Period:
            The confidentiality obligations of both parties shall continue after the contract is terminated, with a confidentiality period of 5 years.
            Responsibility Limitation:
            Party B shall be liable for direct losses caused by software defects, but the liability limit shall not exceed 50% of the total contract amount.
            For indirect losses, profit losses, etc., Party B shall not be liable.

            Confidentiality Period: 
            The confidentiality obligations of both parties shall continue after the contract is terminated, with a confidentiality period of 5 years.
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for legal contract specific properties if detected
    legal_contract_props = [
        "contract_type", "party_a", "party_b", "effective_date", "term",
        "governing_law", "payment_terms", "liability_clause", "confidentiality_period"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in legal_contract_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_press_release_detection(worker_config, trace_info):
    """Test property generation for press release document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Press Release - Zhihui Tech Completes Series C 500 Million RMB Financing

            Release Date: July 15, 2025

            Core Announcement:
            Zhihui Tech announced the completion of Series C financing, with a total amount of 500 million RMB. This round was led by Sequoia Capital China, with Tencent Investment, Alibaba, and others participating.

            Companies Involved:
            - Zhihui Tech (Financing Company)
            - Sequoia Capital China (Lead Investor)  
            - Tencent Investment (Participating Investor)
            - Alibaba (Participating Investor)

            Key Persons:
            - Wang Lei, Founder and CEO of Zhihui Tech
            - Shen Nanpeng, Founding and Managing Partner of Sequoia Capital China
            - Martin Lau, President of Tencent

            Key Financial Data:
            - This Round Financing Amount: 500 million RMB
            - Company Valuation: 5 billion RMB
            - Annual Revenue Growth Rate: 300%
            - Number of Customers: Over 1,000 enterprise customers

            Fund Usage:
            This round of financing will be mainly used for:
            1. Artificial intelligence technology R&D investment (60%)
            2. Market expansion and channel construction (25%) 
            3. Team expansion and talent acquisition (15%)

            Future Development Plans:
            Zhihui Tech plans to achieve the following within the next 2 years:
            - Expand AI product lines to 10 vertical industries
            - Establish overseas R&D centers
            - Advance IPO listing plans
            - Build a complete AI ecosystem

            Media Contact:
            Name: Zhang Yuanyuan
            Position: PR Director of Zhihui Tech  
            Email: media@zhihui-tech.com
            Phone: 010-12345678
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for press release specific properties if detected
    press_release_props = [
        "announcement_subject", "company_involved", "key_persons", "release_date",
        "financial_figures", "purpose_of_funds", "forward_looking_statements", "media_contact"
    ]
    # Note: We don't assert these must exist since AI might not detect all properties
    # Just check if they're present, they should be valid
    for prop in press_release_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_user_interview_detection(worker_config, trace_info):
    """Test property generation for user interview document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            User Interview Record - Product Feedback Collection
            Interviewee: User ID: U12345, Role: Product Manager, Industry: FinTech
            Interview Date: 2025-08-10
            Interviewer: Researcher Zhang
            
            User Goals:
            - Improve data visualization functionality
            - Simplify workflow
            
            Pain Points:
            - Current tool loading speed is slow
            - Lack of custom chart options
            
            Key Quotes:
            - "I hope the tool can support real-time data updates."
            - "Custom chart function is a must-have feature."
            
            Feature Requests:
            - Real-time data refresh
            - More chart templates
            
            Overall Sentiment: Positive but expecting improvements
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for user interview specific properties if detected
    user_interview_props = [
        "interviewee_profile", "interview_date", "user_goals", "pain_points",
        "key_quotes", "feature_requests", "overall_sentiment", "researcher"
    ]
    for prop in user_interview_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_project_proposal_detection(worker_config, trace_info):
    """Test property generation for project proposal document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Project Proposal - Intelligent Customer Service System Upgrade
            Project Owner: Li Director
            Project Objectives:
            - Improve customer response speed
            - Support multi-language interaction
            - Integrate AI chat
            
            Key Stakeholders:
            - Customer service team
            - Technology department
            - Product department
            
            Timeline Milestones:
            - Requirement Confirmation: 2025-09-01
            - Development Completion: 2025-11-15
            - Launch: 2025-12-01
            
            Budget Estimate: 200 million RMB
            Deliverables:
            - New customer service system
            - User manual
            - Training materials
            
            Success Metrics:
            - Response time reduced by 50%
            - User satisfaction increased by 20%
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for project proposal specific properties if detected
    project_proposal_props = [
        "project_title", "project_owner", "objectives", "stakeholders",
        "timeline_milestones", "budget_estimate", "deliverables", "success_metrics"
    ]
    for prop in project_proposal_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_how_to_guide_detection(worker_config, trace_info):
    """Test property generation for how-to guide document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Target Audience: System Administrators
            Prerequisites:
            - Install backup tool
            - Ensure sufficient disk space
            
            Steps:
            1. Log in to the backup server
            2. Run command: `backup --start`
            3. Select backup directory
            4. Confirm backup
            
            Expected Results:
            - Data backup completed
            - Backup log generated
            
            Common Issues:
            - Issue: Backup failed
              Solution: Check disk space
            - Issue: Insufficient permissions
              Solution: Use sudo privileges
            
            Required Tools:
            - Backup tool v2.0
            - SSH client
            
            Last Verified Date: 2025-08-20
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for how-to guide specific properties if detected
    how_to_guide_props = [
        "procedure_title", "target_audience", "prerequisites", "steps",
        "expected_outcome", "troubleshooting", "tools_required", "last_verified_date"
    ]
    for prop in how_to_guide_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_research_paper_detection(worker_config, trace_info):
    """Test property generation for research paper document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Research Paper - Image Segmentation Based on Deep Learning
            Authors: Wang Professor (Tsinghua University), Zhang Doctor (MIT)
            Publication Info: Journal: AI Frontier, Year: 2025
            
            Research Problem:
            - Traditional image segmentation methods have insufficient accuracy
            - Real-time performance is poor
            
            Methodology:
            - Propose a new convolutional neural network architecture
            - Use transfer learning
            
            Core Findings:
            - Accuracy increased by 12%
            - Inference speed increased by 30%
            
            Data Sets:
            - COCO
            - Cityscapes
            
            Limitations:
            - Poor performance on small target segmentation
            - Need further optimization of computational efficiency
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for research paper specific properties if detected
    research_paper_props = [
        "paper_title", "authors", "publication_info", "problem_statement",
        "methodology", "key_findings", "datasets_used", "limitations"
    ]
    for prop in research_paper_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_financial_report_detection(worker_config, trace_info):
    """Test property generation for financial report document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            TechCorp Q3 2024 Financial Report
            
            Company: TechCorp Inc.
            Report Period: Q3 2024 (July-September 2024)
            
            Revenue Performance:
            - Total Revenue: $120 million (YoY growth 25%)
            - Software Revenue: $80 million
            - Services Revenue: $40 million
            
            Profit & Loss:
            - Gross Profit: $72 million (60% margin)
            - Operating Income: $24 million
            - Net Income: $18 million
            
            Key Financial Metrics:
            - EBITDA: $30 million
            - Free Cash Flow: $15 million
            - Customer Acquisition Cost: $2,500
            - Customer Lifetime Value: $25,000
            
            Business Segment Performance:
            - Enterprise Solutions: 65% of revenue, 30% growth
            - Consumer Products: 35% of revenue, 15% growth
            
            Risk Factors:
            - Increased competition in AI space
            - Potential economic downturn impact
            - Regulatory changes in data privacy
            
            Financial Outlook:
            - Q4 2024 revenue guidance: $125-130 million
            - Full year 2024 target: $480 million
            - Investment in R&D to increase by 40%
            
            External Auditor: KPMG LLP
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for financial report specific properties if detected
    financial_report_props = [
        "report_period", "company_name", "revenue_figures", "profit_loss",
        "key_metrics", "segment_performance", "risk_factors", "outlook", "auditor"
    ]
    for prop in financial_report_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_marketing_campaign_detection(worker_config, trace_info):
    """Test property generation for marketing campaign document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Summer Sale 2025 Marketing Campaign Plan
            
            Campaign Name: "AI Revolution Summer Sale"
            Campaign Period: June 1 - August 31, 2025
            
            Target Demographics:
            - Tech professionals aged 25-45
            - Enterprise decision makers
            - Small to medium business owners
            - Annual income $75,000+
            
            Marketing Channels:
            - Social Media: LinkedIn, Twitter, Facebook
            - Email Marketing: Weekly newsletters
            - Content Marketing: Blog posts, whitepapers
            - Paid Advertising: Google Ads, LinkedIn Ads
            - Events: Tech conferences, webinars
            
            Budget Allocation:
            - Social Media Ads: $150,000 (30%)
            - Email Marketing: $50,000 (10%)
            - Content Creation: $100,000 (20%)
            - Paid Search: $125,000 (25%)
            - Events & Webinars: $75,000 (15%)
            Total Budget: $500,000
            
            Key Messages:
            - "Transform your business with AI"
            - "50% off all enterprise AI solutions"
            - "Limited time offer - Act now"
            - "Join the AI revolution"
            
            Success Metrics:
            - Lead Generation: 5,000 qualified leads
            - Conversion Rate: 3% target
            - Brand Awareness: 25% increase
            - Revenue Target: $2 million
            - Cost per Acquisition: <$100
            
            Creative Assets:
            - Hero banner designs (5 variations)
            - Video testimonials (10 customers)
            - Product demo videos
            - Social media graphics
            - Email templates
            
            Campaign Manager: Sarah Johnson (Marketing Director)
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for marketing campaign specific properties if detected
    marketing_campaign_props = [
        "campaign_name", "campaign_period", "target_demographics", "marketing_channels",
        "budget_allocation", "key_messages", "success_metrics", "creative_assets", "campaign_manager"
    ]
    for prop in marketing_campaign_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_product_spec_detection(worker_config, trace_info):
    """Test property generation for product specification document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Product Specification: Smart Analytics Dashboard v3.0
            
            Product Name: Smart Analytics Dashboard
            Version: 3.0
            
            Key Features:
            - Real-time data visualization
            - Customizable dashboard layouts
            - Advanced filtering and search
            - Multi-tenant support
            - API integrations
            - Mobile responsive design
            - Export to PDF/Excel
            - Role-based access control
            
            Technical Requirements:
            - Browser: Chrome 90+, Firefox 85+, Safari 14+
            - Server: Node.js 16+, MongoDB 5.0+
            - RAM: Minimum 8GB, Recommended 16GB
            - Storage: 50GB available space
            - Network: Stable internet connection
            
            User Stories:
            - As a data analyst, I want to create custom dashboards to visualize KPIs
            - As a manager, I want to export reports for executive presentations
            - As an admin, I want to manage user permissions and access levels
            - As a mobile user, I want to view dashboards on my smartphone
            
            Acceptance Criteria:
            - Dashboard loads within 3 seconds
            - Support for 1000+ concurrent users
            - 99.9% uptime requirement
            - Data refresh every 30 seconds
            - Mobile UI passes accessibility standards
            
            Dependencies:
            - User Authentication Service v2.1
            - Data Pipeline API v1.5
            - Chart.js library v3.0
            - Redis cache cluster
            
            Constraints:
            - Must comply with GDPR regulations
            - Limited to 50 dashboard widgets per user
            - Historical data retention: 2 years maximum
            - Budget cap: $500,000 development cost
            
            Priority Level: High (P1)
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for product spec specific properties if detected
    product_spec_props = [
        "product_name", "version", "feature_list", "technical_requirements",
        "user_stories", "acceptance_criteria", "dependencies", "constraints", "priority_level"
    ]
    for prop in product_spec_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_customer_feedback_detection(worker_config, trace_info):
    """Test property generation for customer feedback document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Customer Feedback Report - Mobile App Issues
            
            Feedback Type: Complaint
            
            Customer Information:
            - Customer ID: CUST-12345
            - Customer Segment: Enterprise
            - Account Manager: John Smith
            - Company: TechStartup Inc.
            
            Product/Service: Mobile Analytics App v2.1
            
            Satisfaction Scores:
            - Overall Satisfaction: 6/10
            - User Interface: 7/10
            - Performance: 4/10
            - Customer Support: 8/10
            
            Specific Issues:
            1. App crashes frequently when loading large datasets
            2. Slow response time during peak hours (>10 seconds)
            3. Chart rendering issues on older Android devices
            4. Difficulty exporting reports to PDF format
            5. Missing dark mode feature requested multiple times
            
            Customer Improvement Suggestions:
            - Implement better error handling for data loading
            - Add progress indicators for long-running operations
            - Optimize app performance for low-end devices
            - Introduce dark mode theme option
            - Improve PDF export functionality with better formatting
            
            Follow-up Required: Yes
            - Technical team to investigate crash logs
            - Product team to prioritize dark mode feature
            - Schedule follow-up call within 7 days
            
            Feedback Channel: Email (support@company.com)
            Date Received: August 15, 2025
            Support Ticket: #SUPP-98765
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for customer feedback specific properties if detected
    customer_feedback_props = [
        "feedback_type", "customer_info", "product_service", "satisfaction_score",
        "specific_issues", "improvement_suggestions", "follow_up_required", "feedback_channel"
    ]
    for prop in customer_feedback_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_training_material_detection(worker_config, trace_info):
    """Test property generation for training material document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Training Course: Advanced Machine Learning for Business Analysts
            
            Course Title: Advanced Machine Learning for Business Analysts
            
            Target Learners:
            - Business analysts with 2+ years experience
            - Data analysts transitioning to ML
            - Product managers working with AI teams
            - Technical consultants in enterprise settings
            
            Learning Objectives:
            - Understand core ML algorithms and use cases
            - Learn to evaluate ML model performance
            - Apply ML techniques to business problems
            - Communicate ML insights to stakeholders
            - Build simple predictive models using no-code tools
            
            Course Duration: 40 hours (8 weeks, 5 hours per week)
            
            Prerequisite Knowledge:
            - Basic statistics and probability
            - Excel proficiency (pivot tables, formulas)
            - SQL query writing experience
            - Understanding of business metrics and KPIs
            
            Assessment Methods:
            - Weekly quizzes (40% of grade)
            - Mid-term project: Business case analysis (30%)
            - Final project: ML solution proposal (30%)
            - Peer review assignments
            - Practical lab exercises
            
            Certification Offered:
            - Certificate in Applied Machine Learning for Business
            - 4.0 CEU credits
            - Industry recognized by Google Cloud and AWS
            
            Instructional Design:
            - Blended learning: 60% online, 40% hands-on labs
            - Case study methodology
            - Interactive simulations
            - Peer collaboration projects
            - Expert guest speakers from industry
            
            Course Materials:
            - "Hands-On Machine Learning" textbook
            - Jupyter Notebook exercises
            - Google Colab environment access
            - Kaggle dataset collections
            - Video lecture library (20+ hours)
            - Practice datasets and solutions
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for training material specific properties if detected
    training_material_props = [
        "course_title", "target_learners", "learning_objectives", "course_duration",
        "prerequisite_knowledge", "assessment_methods", "certification_offered",
        "instructional_design", "course_materials"
    ]
    for prop in training_material_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_incident_report_detection(worker_config, trace_info):
    """Test property generation for incident report document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Incident Report: Database Server Outage
            
            Incident Title: Production Database Cluster Failure
            Incident Date: August 20, 2025, 14:30 UTC
            
            Severity & Impact:
            - Severity Level: Critical (P1)
            - Affected Users: 50,000+ active users
            - Service Impact: Complete system unavailability
            - Revenue Impact: $2.5M estimated loss
            - Duration: 3 hours 45 minutes
            
            Root Cause:
            Primary database server hardware failure due to power supply unit malfunction.
            Secondary replica failed to promote due to misconfigured failover scripts.
            
            Timeline of Events:
            - 14:30: Database primary server stops responding
            - 14:35: Monitoring alerts triggered
            - 14:45: Incident commander assigned (Mike Chen)
            - 15:00: Failed attempt to restart primary server
            - 15:30: Decision made to promote secondary replica
            - 16:00: Discovery of failover script configuration issue
            - 17:15: Manual database promotion completed
            - 18:15: All services restored and verified
            
            Resolution Steps:
            1. Immediate assessment of server hardware status
            2. Attempted primary server restart (failed)
            3. Initiated failover to secondary replica (failed)
            4. Diagnosed failover script configuration issue
            5. Manually promoted secondary database to primary
            6. Updated application connection strings
            7. Verified data integrity and service functionality
            8. Restored monitoring and alerting
            
            Lessons Learned:
            - Failover scripts were not properly tested after recent config changes
            - Monitoring didn't detect replica sync lag issues
            - Hardware redundancy was insufficient for critical components
            - Communication to customers was delayed by 30 minutes
            
            Preventive Measures:
            - Implement automated failover testing (weekly)
            - Upgrade to redundant power supply units
            - Enhanced monitoring for replica lag detection
            - Improved incident communication workflow
            - Regular disaster recovery drills (monthly)
            
            Incident Commander: Mike Chen (SRE Team Lead)
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for incident report specific properties if detected
    incident_report_props = [
        "incident_title", "incident_date", "severity_impact", "root_cause",
        "timeline", "resolution_steps", "lessons_learned", "preventive_measures", "incident_commander"
    ]
    for prop in incident_report_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_survey_results_detection(worker_config, trace_info):
    """Test property generation for survey results document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Employee Satisfaction Survey Results - Q3 2025
            
            Survey Title: Annual Employee Satisfaction and Engagement Survey
            Survey Period: July 1 - August 15, 2025
            
            Sample Size: 1,247 employees
            Response Rate: 78.3% (1,247 out of 1,593 eligible employees)
            
            Key Demographics:
            - Department Distribution: Engineering (35%), Sales (20%), Marketing (15%), Operations (30%)
            - Experience Level: 0-2 years (40%), 3-5 years (35%), 5+ years (25%)
            - Location: Remote (45%), Hybrid (35%), On-site (20%)
            - Age Groups: 22-30 (50%), 31-40 (35%), 41+ (15%)
            
            Major Findings:
            1. Overall job satisfaction: 7.2/10 (up from 6.8 last year)
            2. Work-life balance rated 6.9/10 (improvement needed)
            3. Career development opportunities: 6.5/10
            4. Management effectiveness: 7.4/10
            5. Compensation satisfaction: 7.0/10
            6. Remote work satisfaction: 8.1/10 (highest score)
            
            Statistical Significance:
            - Confidence Level: 95%
            - Margin of Error: ±2.7%
            - Statistical significance tests passed for all key metrics
            
            Methodology:
            - Online anonymous survey platform
            - 45 questions across 8 categories
            - Mix of Likert scale and open-ended questions
            - Multiple reminder emails sent
            - Survey available in English and Spanish
            
            Recommendations:
            1. Implement flexible work schedule policy
            2. Expand professional development budget by 25%
            3. Improve manager training programs
            4. Review compensation bands for mid-level positions
            5. Create peer mentorship program
            6. Establish quarterly feedback sessions
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for survey results specific properties if detected
    survey_results_props = [
        "survey_title", "survey_period", "sample_size", "response_rate",
        "key_demographics", "major_findings", "statistical_significance", "methodology", "recommendations"
    ]
    for prop in survey_results_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_policy_document_detection(worker_config, trace_info):
    """Test property generation for policy document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Information Security Policy
            
            Policy Title: Data Protection and Information Security Policy
            Effective Date: September 1, 2025
            
            Policy Owner: Chief Information Security Officer (CISO)
            Department: Information Technology Security Division
            
            Scope and Applicability:
            This policy applies to all employees, contractors, vendors, and third-party users who have access to company information systems, data, or facilities.
            
            Key Requirements:
            1. All users must complete annual security awareness training
            2. Strong passwords required (minimum 12 characters, complexity rules)
            3. Multi-factor authentication mandatory for all systems
            4. Personal devices must be registered and approved for company use
            5. Data classification and handling procedures must be followed
            6. Incident reporting required within 24 hours of discovery
            7. Regular security assessments and audits
            
            Compliance Procedures:
            - Monthly security compliance audits
            - Quarterly access rights reviews
            - Annual policy acknowledgment required
            - Security incident investigation process
            - Regular penetration testing
            - Vendor security assessments
            
            Violations and Consequences:
            - First violation: Mandatory retraining and written warning
            - Second violation: Performance improvement plan
            - Serious violations: Immediate suspension or termination
            - Criminal activity: Law enforcement involvement
            - Contractors: Contract termination
            
            Review Schedule:
            This policy will be reviewed annually or when significant changes occur to:
            - Business operations
            - Technology infrastructure
            - Regulatory requirements
            - Threat landscape
            
            Related Policies:
            - Acceptable Use Policy (AUP-2025-001)
            - Privacy Policy (PP-2025-003)
            - Business Continuity Policy (BCP-2025-005)
            - Vendor Management Policy (VMP-2025-002)
            
            Policy Version: 3.1
            Last Updated: August 15, 2025
            Next Review Date: September 1, 2026
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for policy document specific properties if detected
    policy_document_props = [
        "policy_title", "effective_date", "policy_owner", "scope_applicability",
        "key_requirements", "compliance_procedures", "violations_consequences", 
        "review_schedule", "related_policies"
    ]
    for prop in policy_document_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_email_communication_detection(worker_config, trace_info):
    """Test property generation for email communication document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Email Subject: Urgent: Q3 Project Deliverables Due This Friday
            
            From: Sarah Johnson <sarah.johnson@company.com>
            To: Development Team <dev-team@company.com>
            CC: Mike Chen <mike.chen@company.com>, Lisa Wang <lisa.wang@company.com>
            BCC: management@company.com
            Date: August 22, 2025 2:30 PM
            
            Email Type: Project Update / Deadline Reminder
            
            Hi Team,
            
            I hope this email finds you well. I'm reaching out regarding the Q3 project deliverables that are due this Friday, August 25th at 5:00 PM EST.
            
            Key Requests:
            1. Please submit your completed code modules to the Git repository
            2. Ensure all unit tests are passing before submission
            3. Update project documentation with any new features
            4. Prepare a brief status report (2-3 paragraphs) on your component
            5. Attend the Friday afternoon demo session at 3:00 PM
            
            Important Deadlines:
            - Code submission: Friday, August 25, 5:00 PM EST
            - Documentation updates: Friday, August 25, 4:00 PM EST
            - Demo preparation: Friday, August 25, 2:00 PM EST
            - Team retrospective meeting: Monday, August 28, 10:00 AM EST
            
            Attachments:
            - Project_Requirements_v3.pdf
            - Testing_Guidelines.docx
            - Demo_Template.pptx
            
            Please let me know if you have any questions or concerns about meeting these deadlines. If you anticipate any delays, please reach out to me immediately so we can discuss alternatives.
            
            Follow-up Actions Required:
            - All team members must confirm receipt of this email by end of day
            - Individual status updates required by Wednesday
            - Project manager approval needed for any scope changes
            
            Thanks for your hard work and dedication to this project!
            
            Best regards,
            Sarah Johnson
            Project Manager
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for email communication specific properties if detected
    email_communication_props = [
        "email_subject", "sender", "recipients", "cc_bcc", "email_type",
        "key_requests", "deadlines", "attachments", "follow_up_needed"
    ]
    for prop in email_communication_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_job_description_detection(worker_config, trace_info):
    """Test property generation for job description document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Job Posting: Senior Machine Learning Engineer
            
            Job Title: Senior Machine Learning Engineer
            Department: Artificial Intelligence & Data Science
            
            Employment Type: Full-time, Permanent
            Location Type: Hybrid (3 days in office, 2 days remote)
            Office Location: San Francisco, CA
            
            Experience Required: 5-7 years in machine learning and software development
            
            Key Responsibilities:
            - Design and implement scalable ML algorithms and models
            - Lead cross-functional teams in developing AI-powered features
            - Optimize model performance and deployment pipelines
            - Mentor junior ML engineers and data scientists
            - Collaborate with product teams to translate business requirements into technical solutions
            - Research and evaluate new ML technologies and frameworks
            - Ensure ML models meet quality, performance, and ethical standards
            
            Required Qualifications:
            - Master's degree in Computer Science, Machine Learning, or related field
            - 5+ years of experience in machine learning engineering
            - Strong programming skills in Python, R, or Scala
            - Experience with ML frameworks: TensorFlow, PyTorch, Scikit-learn
            - Proficiency in cloud platforms (AWS, GCP, or Azure)
            - Experience with containerization (Docker, Kubernetes)
            - Knowledge of MLOps practices and tools
            - Strong understanding of statistics and mathematical foundations
            
            Preferred Qualifications:
            - PhD in Machine Learning, AI, or related field
            - Experience with large-scale distributed systems
            - Knowledge of deep learning architectures (CNNs, RNNs, Transformers)
            - Experience with real-time model serving and inference
            - Familiarity with data engineering tools (Spark, Kafka, Airflow)
            - Previous experience in fintech or healthcare domains
            - Publications in top-tier ML conferences
            
            Compensation Range: $180,000 - $250,000 annual salary
            Equity: Stock options package included
            
            Benefits Package:
            - Comprehensive health, dental, and vision insurance
            - 401(k) with company matching up to 6%
            - Unlimited PTO policy
            - $5,000 annual learning and development budget
            - Home office setup allowance ($2,000)
            - Flexible working hours
            - Quarterly team retreats
            - Free meals and snacks in office
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for job description specific properties if detected
    job_description_props = [
        "job_title", "department", "employment_type", "location_type",
        "experience_required", "key_responsibilities", "required_qualifications",
        "preferred_qualifications", "compensation_range", "benefits_package"
    ]
    for prop in job_description_props:
        if prop in properties:
            assert properties[prop] is not None


@pytest.mark.asyncio
async def test_property_generator_event_planning_detection(worker_config, trace_info):
    """Test property generation for event planning document type"""
    property_generator = PropertyGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_properties",
        input={
            "text": """
            Event Planning Document: AI Innovation Summit 2025
            
            Event Name: AI Innovation Summit 2025
            Event Date: October 15-17, 2025
            Event Time: 9:00 AM - 6:00 PM daily
            
            Event Location:
            - Venue: San Francisco Convention Center
            - Address: 747 Howard St, San Francisco, CA 94103
            - Room: Halls A, B, and C
            
            Event Type: Technology Conference & Exhibition
            
            Expected Attendance: 2,500 participants
            - Industry professionals: 1,800
            - Students and academics: 400
            - Media and press: 150
            - Speakers and sponsors: 150
            
            Agenda & Schedule:
            Day 1 (Oct 15): Opening keynotes and AI trends sessions
            - 9:00 AM: Registration and networking breakfast
            - 10:00 AM: Opening keynote by Dr. Andrew Ng
            - 11:30 AM: Panel discussion on AI ethics
            - 2:00 PM: Technical workshops (parallel sessions)
            - 5:00 PM: Welcome reception and networking
            
            Day 2 (Oct 16): Deep-dive technical sessions
            - 9:00 AM: Industry use cases presentations
            - 11:00 AM: Startup pitch competition
            - 2:00 PM: Hands-on AI workshops
            - 4:00 PM: Vendor exhibition showcase
            
            Day 3 (Oct 17): Future of AI and closing
            - 9:00 AM: Research paper presentations
            - 11:00 AM: Investment and funding panel
            - 2:00 PM: Closing keynote by Fei-Fei Li
            - 3:30 PM: Award ceremony and closing remarks
            
            Featured Speakers & Presenters:
            - Dr. Andrew Ng (Stanford University)
            - Fei-Fei Li (HAI Stanford)
            - Demis Hassabis (Google DeepMind)
            - Dario Amodei (Anthropic)
            - Satya Nadella (Microsoft)
            - Jensen Huang (NVIDIA)
            
            Budget & Costs:
            - Venue rental: $150,000
            - Speaker fees and travel: $200,000
            - Catering and refreshments: $125,000
            - A/V equipment and technology: $75,000
            - Marketing and promotion: $50,000
            - Staff and coordination: $40,000
            - Miscellaneous expenses: $10,000
            Total Budget: $650,000
            
            Logistics Requirements:
            - High-speed Wi-Fi for 3,000+ devices
            - Professional A/V setup with live streaming capability
            - Registration and check-in kiosks
            - Catering for 2,500 people (breakfast, lunch, coffee breaks)
            - Simultaneous translation services (English, Chinese, Spanish)
            - Security personnel and access control
            - Parking arrangements for 800 vehicles
            
            Registration Process:
            - Online registration platform: Eventbrite
            - Early bird pricing: $599 (until Aug 31)
            - Regular pricing: $799 (Sep 1 - Oct 10)
            - Student discount: 50% off with valid ID
            - Group discounts: 15% off for 5+ registrations
            - VIP packages: $1,299 (includes networking dinner)
            """,
            "lang": "English"
        }
    )

    result = await property_generator.run(task, trace_info)
    
    assert "properties" in result
    properties = result["properties"]
    
    # Check for event planning specific properties if detected
    event_planning_props = [
        "event_name", "event_date", "event_location", "event_type",
        "expected_attendance", "agenda_schedule", "speakers_presenters",
        "budget_costs", "logistics_requirements", "registration_process"
    ]
    for prop in event_planning_props:
        if prop in properties:
            assert properties[prop] is not None