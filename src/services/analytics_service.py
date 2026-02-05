from datetime import datetime, timedelta
from src.db.mongo import get_db

class AnalyticsService:
    async def get_tenant_stats(self, tenant_id: str, from_date: datetime = None, to_date: datetime = None) -> dict:
        """
        Compute analytics for a tenant within a date range.
        
        Task 3: Uses MongoDB aggregation pipeline for high performance.
        Target: <500ms for 10k+ tickets (optimized with indexes).
        All calculations done in the database, no Python processing.
        """
        db = await get_db()
        
        # Default date range: last 60 days if not specified
        if not to_date:
            to_date = datetime.utcnow()
        if not from_date:
            from_date = to_date - timedelta(days=60)
        
        # Build match query
        match_query = {
            "tenant_id": tenant_id,
            "deleted_at": {"$exists": False},  # Exclude soft-deleted tickets
            "created_at": {"$gte": from_date, "$lte": to_date}
        }
        
        # Single aggregation pipeline that computes all metrics
        pipeline = [
            # Stage 1: Filter tickets
            {"$match": match_query},
            
            # Stage 2: Compute all stats in one pass using $facet
            {
                "$facet": {
                    # Total count
                    "total": [
                        {"$count": "count"}
                    ],
                    
                    # Count by status
                    "by_status": [
                        {
                            "$group": {
                                "_id": "$status",
                                "count": {"$sum": 1}
                            }
                        }
                    ],
                    
                    # Urgency metrics
                    "urgency_stats": [
                        {
                            "$group": {
                                "_id": "$urgency",
                                "count": {"$sum": 1}
                            }
                        }
                    ],
                    
                    # Sentiment metrics
                    "sentiment_stats": [
                        {
                            "$group": {
                                "_id": "$sentiment",
                                "count": {"$sum": 1}
                            }
                        }
                    ],
                    
                    # Hourly trend for last 24 hours
                    "hourly_trend": [
                        {
                            "$match": {
                                "created_at": {"$gte": datetime.utcnow() - timedelta(hours=24)}
                            }
                        },
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d %H:00:00",
                                        "date": "$created_at"
                                    }
                                },
                                "count": {"$sum": 1}
                            }
                        },
                        {"$sort": {"_id": 1}},
                        {"$limit": 24}
                    ],
                    
                    # Top keywords from messages (simple word frequency)
                    "keywords": [
                        {
                            "$project": {
                                "words": {
                                    "$split": [
                                        {"$toLower": "$message"},
                                        " "
                                    ]
                                }
                            }
                        },
                        {"$unwind": "$words"},
                        {
                            "$match": {
                                "words": {
                                    "$nin": ["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were", ""],
                                    "$regex": "^[a-z]{4,}$"  # At least 4 letters
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": "$words",
                                "count": {"$sum": 1}
                            }
                        },
                        {"$sort": {"count": -1}},
                        {"$limit": 10}
                    ],
                    
                    # At-risk customers (customers with multiple high urgency tickets)
                    "at_risk": [
                        {
                            "$match": {
                                "urgency": "high"
                            }
                        },
                        {
                            "$group": {
                                "_id": "$customer_id",
                                "high_urgency_count": {"$sum": 1},
                                "ticket_ids": {"$push": "$external_id"}
                            }
                        },
                        {
                            "$match": {
                                "high_urgency_count": {"$gte": 2}
                            }
                        },
                        {"$sort": {"high_urgency_count": -1}},
                        {"$limit": 10}
                    ]
                }
            }
        ]
        
        # Execute aggregation
        cursor = db.tickets.aggregate(pipeline)
        results = await cursor.to_list(length=1)
        
        if not results:
            return self._empty_stats()
        
        facet_results = results[0]
        
        # Parse results
        total_count = facet_results["total"][0]["count"] if facet_results["total"] else 0
        
        # Build by_status dict
        by_status = {}
        for item in facet_results.get("by_status", []):
            by_status[item["_id"]] = item["count"]
        
        # Calculate urgency_high_ratio
        urgency_high_count = 0
        for item in facet_results.get("urgency_stats", []):
            if item["_id"] == "high":
                urgency_high_count = item["count"]
        urgency_high_ratio = urgency_high_count / total_count if total_count > 0 else 0.0
        
        # Calculate negative_sentiment_ratio
        negative_sentiment_count = 0
        for item in facet_results.get("sentiment_stats", []):
            if item["_id"] == "negative":
                negative_sentiment_count = item["count"]
        negative_sentiment_ratio = negative_sentiment_count / total_count if total_count > 0 else 0.0
        
        # Format hourly trend
        hourly_trend = [
            {"hour": item["_id"], "count": item["count"]}
            for item in facet_results.get("hourly_trend", [])
        ]
        
        # Format top keywords
        top_keywords = [item["_id"] for item in facet_results.get("keywords", [])]
        
        # Format at-risk customers
        at_risk_customers = [
            {
                "customer_id": item["_id"],
                "high_urgency_count": item["high_urgency_count"],
                "ticket_ids": item["ticket_ids"]
            }
            for item in facet_results.get("at_risk", [])
        ]
        
        return {
            "total_tickets": total_count,
            "by_status": by_status,
            "urgency_high_ratio": round(urgency_high_ratio, 3),
            "negative_sentiment_ratio": round(negative_sentiment_ratio, 3),
            "hourly_trend": hourly_trend,
            "top_keywords": top_keywords,
            "at_risk_customers": at_risk_customers
        }
    
    def _empty_stats(self) -> dict:
        """Return empty stats when no data is available."""
        return {
            "total_tickets": 0,
            "by_status": {},
            "urgency_high_ratio": 0.0,
            "negative_sentiment_ratio": 0.0,
            "hourly_trend": [],
            "top_keywords": [],
            "at_risk_customers": []
        }
