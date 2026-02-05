class ClassifyService:
    @staticmethod
    def classify(message: str, subject: str) -> dict:
        """
        Rule-based classification for urgency, sentiment, and actionability.
        Enhanced with comprehensive keyword matching for production use.
        """
        # Combine subject and message for analysis, convert to lowercase
        text = (subject + " " + message).lower()

        # Urgency Classification
        urgency = "low"
        
        # High urgency keywords - critical issues requiring immediate attention
        high_urgency_keywords = [
            "urgent", "critical", "emergency", "asap", "immediately",
            "lawsuit", "legal", "lawyer", "attorney", "court",
            "refund", "chargeback", "fraud", "security breach",
            "data breach", "gdpr", "compliance", "violation",
            "outage", "down", "not working", "broken", "crashed"
        ]
        
        # Medium urgency keywords
        medium_urgency_keywords = [
            "issue", "problem", "error", "bug", "concern",
            "complaint", "unhappy", "dissatisfied", "disappointed"
        ]
        
        if any(keyword in text for keyword in high_urgency_keywords):
            urgency = "high"
        elif any(keyword in text for keyword in medium_urgency_keywords):
            urgency = "medium"

        # Sentiment Analysis
        sentiment = "neutral"
        
        # Negative sentiment keywords
        negative_keywords = [
            "angry", "frustrated", "terrible", "awful", "horrible",
            "worst", "hate", "useless", "broken", "disappointed",
            "unacceptable", "poor", "bad", "annoyed", "upset"
        ]
        
        # Positive sentiment keywords
        positive_keywords = [
            "thank", "thanks", "appreciate", "great", "excellent",
            "good", "happy", "satisfied", "wonderful", "love"
        ]
        
        if any(keyword in text for keyword in negative_keywords):
            sentiment = "negative"
        elif any(keyword in text for keyword in positive_keywords):
            sentiment = "positive"

        # Requires Action - tickets that need immediate response
        requires_action = False
        
        action_required_keywords = [
            "refund", "cancel", "delete", "remove", "fix",
            "help", "urgent", "asap", "immediately",
            "lawsuit", "legal", "gdpr", "compliance",
            "broken", "not working", "error", "issue"
        ]
        
        if any(keyword in text for keyword in action_required_keywords):
            requires_action = True

        return {
            "urgency": urgency,
            "sentiment": sentiment,
            "requires_action": requires_action,
        }
