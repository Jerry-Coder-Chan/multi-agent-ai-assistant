"""
Security_Agent.py - Palo Alto Networks Prisma AIRS Runtime Security Integration

This agent monitors all AI interactions for security threats using AIRS API.
Integrates with Strata Cloud Manager for centralized security management.
"""

import requests
import logging
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AIRSResponse:
    """Structured response from AIRS scan"""
    is_safe: bool
    threat_detected: bool
    threat_type: Optional[str] = None
    risk_score: Optional[float] = None
    action_taken: str = "ALLOW"
    scan_time_ms: Optional[float] = None
    details: Optional[Dict] = None


class SecurityAgent:
    """
    Palo Alto Networks AIRS Security Agent
    
    Monitors AI prompts and responses for:
    - Prompt injection attacks
    - Data exfiltration attempts
    - Malicious content
    - PII exposure
    - Jailbreak attempts
    """
    
    # AIRS API Configuration
    AIRS_BASE_URL = "https://service.api.aisecurity.paloaltonetworks.com"
    AIRS_SYNC_ENDPOINT = "/v1/scan/sync/request"
    
    # Application Configuration (from Strata Cloud Manager)
    APP_NAME = "multi-agent-ai-assistant"
    DEPLOYMENT_PROFILE = "ezhi-airs-api-profile"
    
    def __init__(
        self, 
        api_key: str,
        enable_prompt_scan: bool = True,
        enable_response_scan: bool = True,
        block_on_threat: bool = False,
        timeout: int = 5
    ):
        """
        Initialize Security Agent with AIRS
        
        Args:
            api_key: AIRS API Key from Strata Cloud Manager
            enable_prompt_scan: Scan user prompts for threats
            enable_response_scan: Scan AI responses for threats
            block_on_threat: Block requests when threats detected (vs log only)
            timeout: API timeout in seconds
        """
        self.api_key = api_key
        self.enable_prompt_scan = enable_prompt_scan
        self.enable_response_scan = enable_response_scan
        self.block_on_threat = block_on_threat
        self.timeout = timeout
        
        # Track activation status
        self.activation_status = "unknown"
        self.last_error = None
        
        # Statistics tracking
        self.stats = {
            "total_scans": 0,
            "threats_detected": 0,
            "prompts_scanned": 0,
            "responses_scanned": 0,
            "blocked_requests": 0
        }
        
        # Validate API key
        if not api_key or api_key == "":
            logger.warning("AIRS API Key not provided - Security monitoring DISABLED")
            self.enabled = False
            self.activation_status = "disabled"
        else:
            self.enabled = True
            self.activation_status = "pending"
            logger.info(f"Security Agent initialized - App: {self.APP_NAME}, Profile: {self.DEPLOYMENT_PROFILE}")
    
    def scan_interaction(
        self, 
        prompt: str, 
        response: Optional[str] = None,
        ai_model: str = "gpt-4",
        app_user: str = "anonymous",
        agent_name: str = "controller"
    ) -> AIRSResponse:
        """
        Scan AI prompt and/or response for security threats
        
        Args:
            prompt: User input prompt
            response: AI generated response (optional)
            ai_model: Model being used (e.g., gpt-4, gpt-3.5-turbo)
            app_user: User identifier (session ID, username, etc.)
            agent_name: Which agent is handling this (for tracking)
            
        Returns:
            AIRSResponse object with scan results
        """
        if not self.enabled:
            return AIRSResponse(
                is_safe=True,
                threat_detected=False,
                action_taken="SKIP_DISABLED"
            )
        
        # Determine what to scan
        scan_prompt = self.enable_prompt_scan and prompt
        scan_response = self.enable_response_scan and response
        
        if not scan_prompt and not scan_response:
            return AIRSResponse(
                is_safe=True,
                threat_detected=False,
                action_taken="SKIP_CONFIG"
            )
        
        try:
            start_time = time.time()
            
            # Build AIRS API request
            airs_request = self._build_airs_request(
                prompt=prompt if scan_prompt else "",
                response=response if scan_response else "",
                ai_model=ai_model,
                app_user=app_user,
                agent_name=agent_name
            )
            
            # Call AIRS API
            airs_response = self._call_airs_api(airs_request)
            
            # Parse response
            scan_result = self._parse_airs_response(airs_response)
            scan_result.scan_time_ms = (time.time() - start_time) * 1000
            
            # Update statistics
            self._update_stats(scan_result, scan_prompt, scan_response)
            
            # Log results
            self._log_scan_result(scan_result, prompt, response, agent_name)
            
            # Mark as activated on first successful scan
            if self.activation_status == "pending":
                self.activation_status = "active"
                self.last_error = None
            
            return scan_result
            
        except requests.exceptions.HTTPError as e:
            # Handle HTTP errors specifically
            if e.response.status_code == 403:
                self.activation_status = "pending_activation"
                self.last_error = "API key pending activation. Contact Palo Alto support."
                logger.error(f"AIRS 403 Forbidden - Account not activated: {str(e)}")
            elif e.response.status_code == 401:
                self.activation_status = "auth_failed"
                self.last_error = "Authentication failed. Check API key."
                logger.error(f"AIRS 401 Unauthorized: {str(e)}")
            else:
                self.activation_status = "error"
                self.last_error = f"HTTP {e.response.status_code}: {str(e)}"
                logger.error(f"AIRS HTTP error: {str(e)}")
            
            return AIRSResponse(
                is_safe=True,  # Fail open
                threat_detected=False,
                action_taken="ERROR",
                details={"error": str(e), "status_code": e.response.status_code}
            )
            
        except requests.exceptions.Timeout:
            self.activation_status = "timeout"
            self.last_error = f"API timeout after {self.timeout}s"
            logger.error(f"AIRS API timeout after {self.timeout}s")
            return AIRSResponse(
                is_safe=True,  # Fail open
                threat_detected=False,
                action_taken="TIMEOUT",
                details={"error": "API timeout"}
            )
            
        except Exception as e:
            self.activation_status = "error"
            self.last_error = str(e)
            logger.error(f"AIRS scan error: {str(e)}")
            return AIRSResponse(
                is_safe=True,  # Fail open
                threat_detected=False,
                action_taken="ERROR",
                details={"error": str(e)}
            )
    
    def _build_airs_request(
        self,
        prompt: str,
        response: str,
        ai_model: str,
        app_user: str,
        agent_name: str
    ) -> Dict:
        """Build AIRS API request payload"""
        
        # Generate unique transaction ID
        tr_id = f"{int(time.time() * 1000)}_{agent_name}"
        
        request_payload = {
            "metadata": {
                "ai_model": ai_model,
                "app_name": self.APP_NAME,
                "app_user": app_user,
                "agent_name": agent_name,
                "timestamp": datetime.utcnow().isoformat()
            },
            "contents": [
                {
                    "prompt": prompt,
                    "response": response
                }
            ],
            "tr_id": tr_id,
            "ai_profile": {
                "profile_name": self.DEPLOYMENT_PROFILE
            }
        }
        
        return request_payload
    
    def _call_airs_api(self, request_payload: Dict) -> Dict:
        """Make synchronous call to AIRS API"""

        # Store last request payload for debugging/visibility
        self.last_request_payload = request_payload

        url = f"{self.AIRS_BASE_URL}{self.AIRS_SYNC_ENDPOINT}"
        
        headers = {
            "Content-Type": "application/json",
            "x-pan-token": self.api_key
        }
        
        response = requests.post(
            url,
            headers=headers,
            json=request_payload,
            timeout=self.timeout,
            verify=True
        )
        
        response.raise_for_status()
        return response.json()
    
    def _parse_airs_response(self, airs_response: Dict) -> AIRSResponse:
        """Parse AIRS API response into structured format"""
        
        try:
            status = airs_response.get("status", "unknown")
            threats = airs_response.get("threats", [])
            risk_score = airs_response.get("risk_score", 0)
            action = airs_response.get("action", "allow")

            # Support AIRS responses that report in "details"
            details = airs_response.get("details", {})
            category = details.get("category")
            details_action = details.get("action")
            prompt_detected = details.get("prompt_detected", {}) or {}
            response_detected = details.get("response_detected", {}) or {}
            detected_flags = list(prompt_detected.values()) + list(response_detected.values())
            detected_any = any(bool(v) for v in detected_flags)

            if details_action:
                action = details_action

            threat_detected = (
                len(threats) > 0
                or status == "threat"
                or detected_any
                or (category and category.lower() != "benign")
                or (action and action.lower() == "block")
            )
            is_safe = not threat_detected or action.lower() == "allow"
            if threats:
                threat_type = threats[0].get("type")
            elif category:
                threat_type = category
            else:
                threat_type = next((k for k, v in {**prompt_detected, **response_detected}.items() if v), None)
            
            if threat_detected and self.block_on_threat:
                action_taken = "BLOCKED"
            elif threat_detected:
                action_taken = "LOGGED"
            else:
                action_taken = "ALLOW"
            
            return AIRSResponse(
                is_safe=is_safe,
                threat_detected=threat_detected,
                threat_type=threat_type,
                risk_score=risk_score,
                action_taken=action_taken,
                details=airs_response
            )
            
        except Exception as e:
            logger.error(f"Error parsing AIRS response: {str(e)}")
            return AIRSResponse(
                is_safe=True,
                threat_detected=False,
                action_taken="PARSE_ERROR",
                details={"error": str(e), "raw_response": airs_response}
            )
    
    def _update_stats(self, scan_result: AIRSResponse, scanned_prompt: bool, scanned_response: bool):
        """Update internal statistics"""
        self.stats["total_scans"] += 1
        
        if scanned_prompt:
            self.stats["prompts_scanned"] += 1
        
        if scanned_response:
            self.stats["responses_scanned"] += 1
        
        if scan_result.threat_detected:
            self.stats["threats_detected"] += 1
        
        if scan_result.action_taken == "BLOCKED":
            self.stats["blocked_requests"] += 1
    
    def _log_scan_result(
        self, 
        scan_result: AIRSResponse, 
        prompt: str, 
        response: Optional[str],
        agent_name: str
    ):
        """Log scan results for monitoring"""
        
        if scan_result.threat_detected:
            logger.warning(
                f"THREAT DETECTED | Agent: {agent_name} | "
                f"Type: {scan_result.threat_type} | "
                f"Risk: {scan_result.risk_score} | "
                f"Action: {scan_result.action_taken}"
            )
        else:
            logger.info(
                f"Scan OK | Agent: {agent_name} | "
                f"Time: {scan_result.scan_time_ms:.2f}ms"
            )
    
    def get_safe_response(self, threat_type: Optional[str] = None) -> str:
        """Generate safe response when threat is blocked"""
        
        base_message = (
            "I'm sorry, but I cannot process this request as it may violate "
            "our security policies. "
        )
        
        if threat_type:
            type_messages = {
                "prompt_injection": "The input appears to contain prompt injection attempts.",
                "data_exfiltration": "The request may attempt to extract sensitive data.",
                "malicious_content": "The content has been flagged as potentially malicious.",
                "jailbreak": "The request appears to bypass safety guidelines.",
                "pii_exposure": "The interaction may expose personally identifiable information."
            }
            
            specific_message = type_messages.get(
                threat_type.lower(), 
                "The request has been flagged for security review."
            )
            
            return base_message + specific_message
        
        return base_message + "Please rephrase your request or contact support if you believe this is an error."
    
    def get_statistics(self) -> Dict:
        """Get security statistics"""
        return {
            **self.stats,
            "threat_rate": (
                self.stats["threats_detected"] / self.stats["total_scans"] * 100
                if self.stats["total_scans"] > 0 else 0
            ),
            "enabled": self.enabled,
            "activation_status": self.activation_status,
            "last_error": self.last_error,
            "config": {
                "app_name": self.APP_NAME,
                "deployment_profile": self.DEPLOYMENT_PROFILE,
                "scan_prompts": self.enable_prompt_scan,
                "scan_responses": self.enable_response_scan,
                "block_threats": self.block_on_threat
            }
        }
    
    def health_check(self) -> Tuple[bool, str]:
        """
        Perform health check on AIRS connection
        
        Returns:
            Tuple of (is_healthy, status_message)
        """
        if not self.enabled:
            return False, "Security Agent disabled (no API key)"
        
        try:
            test_result = self.scan_interaction(
                prompt="health check test",
                response="test response",
                app_user="health_check"
            )
            
            if test_result.action_taken in ["ALLOW", "LOGGED"]:
                return True, f"AIRS connection healthy (scan time: {test_result.scan_time_ms:.0f}ms)"
            elif self.activation_status == "pending_activation":
                return False, "⚠️ AIRS pending activation - Contact Palo Alto support"
            elif self.activation_status == "auth_failed":
                return False, "⚠️ AIRS authentication failed - Check API key"
            else:
                return False, f"⚠️ AIRS connection issue: {self.last_error or test_result.action_taken}"
                
        except Exception as e:
            return False, f"⚠️ AIRS health check failed: {str(e)}"
