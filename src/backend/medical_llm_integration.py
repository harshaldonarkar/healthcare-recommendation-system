# src/backend/medical_llm_integration.py

import requests
import json
import os
import logging
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_MEDGEMMA_SYSTEM = (
    "You are MedGemma, a medical AI assistant trained by Google on clinical literature. "
    "Provide accurate, evidence-based medical information in clear, patient-friendly language. "
    "Always remind users that your responses are informational and do not replace professional medical advice."
)


class MedicalLLMIntegration:
    """Enhanced integration for medical-specific LLMs.

    Supported providers: "huggingface", "openai", "anthropic", "medgemma"
    """

    def __init__(self, provider="huggingface"):
        self.provider = provider

        # Hugging Face settings
        self.hf_api_url = "https://api-inference.huggingface.co/models"
        self.hf_model = os.environ.get("HF_MODEL", "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext")
        self.hf_api_key = os.environ.get("HF_API_KEY", "")

        # OpenAI settings
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o")

        # Anthropic settings
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        # MedGemma settings
        # Set MEDGEMMA_LOCAL=true to run the model on-device (requires ~8 GB RAM + transformers).
        # Otherwise uses the HuggingFace Serverless Inference API (needs HF_API_KEY).
        self.medgemma_model = os.environ.get("MEDGEMMA_MODEL", "google/medgemma-4b-it")
        self.medgemma_local = os.environ.get("MEDGEMMA_LOCAL", "false").lower() == "true"
        self._medgemma_pipeline = None   # lazy-loaded on first call

        logger.info(f"Medical LLM integration initialized with provider: {provider}")
    
    def generate_patient_friendly_explanation(self, disease: str, symptoms: str, medical_info: Dict[str, Any]) -> str:
        """
        Generate a patient-friendly explanation of a disease and its symptoms
        
        Args:
            disease: The diagnosed disease
            symptoms: The symptoms described by the patient
            medical_info: Additional medical information (causes, treatments, etc.)
            
        Returns:
            A patient-friendly explanation of the disease
        """
        try:
            # Create a prompt for the LLM
            prompt = self._create_explanation_prompt(disease, symptoms, medical_info)
            
            # Generate response using the selected provider
            explanation = self._get_llm_response(prompt)
            
            return explanation
        except Exception as e:
            logger.error(f"Error generating patient-friendly explanation: {e}")
            # Provide a basic fallback explanation
            return f"{disease} is a medical condition that may cause symptoms like {symptoms}. It's typically caused by {medical_info.get('causes', 'various factors')}. Please consult with a healthcare professional for a comprehensive diagnosis and appropriate treatment."
    
    def analyze_symptoms_with_confidence(self, symptoms: str, predicted_diseases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Provide a medical analysis of the symptoms and the predicted diseases
        
        Args:
            symptoms: The symptoms described by the patient
            predicted_diseases: List of predicted diseases with confidence scores
            
        Returns:
            Enhanced list of predicted diseases with medical analysis
        """
        try:
            # Create a prompt for symptom analysis
            disease_names = [disease["disease"] for disease in predicted_diseases]
            confidence_scores = [f"{disease['disease']}: {disease['confidence']:.1f}%" for disease in predicted_diseases]
            
            prompt = f"""
            Patient symptoms: "{symptoms}"
            
            Based on these symptoms, the following diseases have been predicted with these confidence scores:
            {', '.join(confidence_scores)}
            
            For each disease, please provide:
            1. Why this disease might match these symptoms (symptom correlation)
            2. Important factors to consider for diagnosis
            3. Common symptoms not mentioned that would help confirm this diagnosis
            
            Keep the analysis concise, factual, and medically accurate. Focus only on symptoms and diagnostic indications, not treatment recommendations.
            """
            
            # Get LLM response
            full_analysis = self._get_llm_response(prompt)
            
            # Add analysis to each predicted disease
            enhanced_predictions = []
            for disease in predicted_diseases:
                disease_name = disease["disease"]
                
                # Extract relevant analysis for this specific disease
                disease_analysis = self._extract_disease_analysis(full_analysis, disease_name)
                
                # Create enhanced prediction with analysis
                enhanced_prediction = disease.copy()
                enhanced_prediction["llm_analysis"] = disease_analysis
                
                enhanced_predictions.append(enhanced_prediction)
            
            return enhanced_predictions
        except Exception as e:
            logger.error(f"Error analyzing symptoms: {e}")
            # Return original predictions without analysis
            return predicted_diseases
    
    def generate_personalized_recommendations(
        self, 
        disease: str, 
        basic_recommendations: Dict[str, Any], 
        user_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate personalized medical recommendations
        
        Args:
            disease: The diagnosed disease
            basic_recommendations: Basic treatment recommendations
            user_profile: User medical profile (optional)
            
        Returns:
            Enhanced recommendations with personalized advice
        """
        try:
            # Extract user profile information or use defaults
            if user_profile:
                allergies = user_profile.get("allergies", [])
                conditions = user_profile.get("conditions", [])
                age = user_profile.get("age", "unknown")
                gender = user_profile.get("gender", "unknown")
            else:
                allergies = []
                conditions = []
                age = "unknown"
                gender = "unknown"
            
            # Create prompt for personalized recommendations
            prompt = f"""
            Based on a diagnosis of {disease}, provide personalized healthcare recommendations.
            
            Basic recommendations:
            - Medications: {', '.join(basic_recommendations.get('medicines', []))}
            - Diet: {basic_recommendations.get('diet', 'Not specified')}
            - Exercise: {basic_recommendations.get('workout', 'Not specified')}
            - Precautions: {', '.join(basic_recommendations.get('precautions', []))}
            
            Patient profile:
            - Age: {age}
            - Gender: {gender}
            - Known allergies: {', '.join(allergies) if allergies else 'None'}
            - Pre-existing conditions: {', '.join(conditions) if conditions else 'None'}
            
            Please provide personalized recommendations in these categories:
            1. Medication considerations (including potential allergies/interactions)
            2. Dietary adjustments specific to this patient's profile
            3. Exercise modifications if needed
            4. Additional precautions or monitoring needed
            5. When to seek additional medical attention
            
            Format your response in a patient-friendly way with short paragraphs and bullet points where appropriate.
            """
            
            # Get LLM response
            personalized_advice = self._get_llm_response(prompt)
            
            # Add personalized recommendations to the basic ones
            enhanced_recommendations = basic_recommendations.copy()
            enhanced_recommendations["personalized_advice"] = personalized_advice
            
            return enhanced_recommendations
        except Exception as e:
            logger.error(f"Error generating personalized recommendations: {e}")
            # Return basic recommendations with generic advice
            basic_recommendations["personalized_advice"] = f"For {disease}, follow the recommended medications, diet, and exercise routine. Monitor your symptoms and consult with a healthcare professional if they worsen or don't improve."
            return basic_recommendations
    
    def _create_explanation_prompt(self, disease: str, symptoms: str, medical_info: Dict[str, Any]) -> str:
        """Create a prompt for generating a patient-friendly explanation"""
        causes = medical_info.get("causes", "Unknown causes")
        common_symptoms = medical_info.get("symptoms", [])
        symptoms_text = ", ".join(common_symptoms) if common_symptoms else "various symptoms"
        
        return f"""
        Please explain the following medical condition to a patient in simple, non-technical language:
        
        Condition: {disease}
        
        Patient's symptoms: {symptoms}
        
        Medical information:
        - Causes: {causes}
        - Common symptoms: {symptoms_text}
        
        Your explanation should:
        1. Describe what {disease} is in simple terms
        2. Explain how it relates to the patient's reported symptoms
        3. Briefly explain what typically causes this condition
        4. Be reassuring and factual without minimizing the condition
        5. Avoid medical jargon or explain it when necessary
        
        Write in a conversational, empathetic tone. Keep your explanation to 3-4 short paragraphs.
        """
    
    def _extract_disease_analysis(self, full_analysis: str, disease_name: str) -> str:
        """Extract the analysis for a specific disease from the full analysis"""
        lines = full_analysis.split("\n")
        disease_section = []
        in_disease_section = False
        
        for line in lines:
            # Check if this line starts a section for our target disease
            if disease_name in line and (":" in line or "-" in line):
                in_disease_section = True
                continue
            
            # Check if we've reached the next disease section
            if in_disease_section and line.strip() and (":" in line or "-" in line) and disease_name not in line:
                # This might be the start of the next disease section
                if any(other_disease in line for other_disease in ["Disease", "Condition", "Diagnosis"]):
                    in_disease_section = False
                    continue
            
            # Add lines while we're in the correct disease section
            if in_disease_section and line.strip():
                disease_section.append(line)
        
        # If we didn't find a clearly formatted section, do a more basic extraction
        if not disease_section:
            sentences = []
            for line in lines:
                if disease_name in line:
                    sentences.append(line.strip())
                    # Add the next line too for context
                    next_index = lines.index(line) + 1
                    if next_index < len(lines):
                        sentences.append(lines[next_index].strip())
            
            disease_section = sentences[:3]  # Limit to first 3 relevant sentences
        
        # Join the extracted lines and clean up
        analysis = " ".join(disease_section).strip()
        
        # If still empty, provide a generic analysis
        if not analysis:
            analysis = f"{disease_name} may be related to the symptoms you're experiencing. Further medical evaluation would be needed to confirm this diagnosis."
        
        return analysis
    
    def _get_llm_response(self, prompt: str) -> str:
        """Get response from selected LLM provider"""
        try:
            logger.info(f"Requesting LLM response from {self.provider}")

            if self.provider == "huggingface":
                return self._get_huggingface_response(prompt)
            elif self.provider == "openai":
                return self._get_openai_response(prompt)
            elif self.provider == "anthropic":
                return self._get_anthropic_response(prompt)
            elif self.provider == "medgemma":
                return self._get_medgemma_response(prompt)
            else:
                raise ValueError(f"Unsupported LLM provider: {self.provider}")
        except Exception as e:
            logger.error(f"Error getting LLM response: {e}")
            return "Unable to generate enhanced medical information. Please rely on the basic information provided."
    
    def _get_huggingface_response(self, prompt: str) -> str:
        """Get response from Hugging Face Inference API"""
        headers = {
            "Authorization": f"Bearer {self.hf_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_length": 512,
                "temperature": 0.7,
                "top_p": 0.9,
                "do_sample": True
            }
        }
        
        response = requests.post(
            f"{self.hf_api_url}/{self.hf_model}",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            # Response format depends on the model
            if isinstance(result, list) and len(result) > 0:
                if "generated_text" in result[0]:
                    return result[0]["generated_text"]
            return str(result)
        else:
            logger.error(f"Hugging Face API error: {response.text}")
            return "Unable to generate enhanced medical information."
    
    def _get_openai_response(self, prompt: str) -> str:
        """Get response from OpenAI API"""
        try:
            import openai
            client = openai.OpenAI(api_key=self.openai_api_key)
            
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are a knowledgeable medical assistant providing helpful, accurate, and patient-friendly healthcare information. Your responses should be medically sound, empathetic, and easy to understand."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message.content
        except ImportError:
            logger.error("OpenAI package not installed. Run 'pip install openai' to use OpenAI.")
            return "OpenAI integration unavailable. Please install the openai package."
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return "Unable to generate enhanced medical information."
    
    def _get_anthropic_response(self, prompt: str) -> str:
        """Get response from Anthropic API"""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            
            response = client.messages.create(
                model=self.anthropic_model,
                max_tokens=500,
                temperature=0.7,
                system="You are a knowledgeable medical assistant providing helpful, accurate, and patient-friendly healthcare information. Your responses should be medically sound, empathetic, and easy to understand.",
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text
        except ImportError:
            logger.error("Anthropic package not installed. Run 'pip install anthropic' to use Anthropic.")
            return "Anthropic integration unavailable. Please install the anthropic package."
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return "Unable to generate enhanced medical information."

    def _get_medgemma_response(self, prompt: str) -> str:
        """Get response from MedGemma (google/medgemma-4b-it).

        Two modes controlled by MEDGEMMA_LOCAL env var:
          • MEDGEMMA_LOCAL=true  — runs the model on-device via transformers (needs ~8 GB RAM).
          • MEDGEMMA_LOCAL=false — calls the HuggingFace Serverless Inference API (needs HF_API_KEY).
        """
        if self.medgemma_local:
            return self._medgemma_local(prompt)
        return self._medgemma_api(prompt)

    def _medgemma_local(self, prompt: str) -> str:
        """On-device MedGemma inference via transformers pipeline."""
        try:
            if self._medgemma_pipeline is None:
                from transformers import pipeline
                import torch

                device = "mps" if torch.backends.mps.is_available() else (
                    "cuda" if torch.cuda.is_available() else "cpu"
                )
                logger.info(f"Loading MedGemma locally on {device}: {self.medgemma_model}")
                self._medgemma_pipeline = pipeline(
                    "text-generation",
                    model=self.medgemma_model,
                    device=device,
                    torch_dtype=torch.bfloat16,
                )

            messages = [
                {"role": "system", "content": _MEDGEMMA_SYSTEM},
                {"role": "user",   "content": prompt},
            ]
            out = self._medgemma_pipeline(
                messages,
                max_new_tokens=512,
                do_sample=True,
                temperature=0.4,
                top_p=0.9,
            )
            # transformers returns the full conversation; grab only the assistant turn
            generated = out[0]["generated_text"]
            if isinstance(generated, list):
                # chat template format: list of message dicts
                for msg in reversed(generated):
                    if msg.get("role") == "assistant":
                        return msg.get("content", "").strip()
            return str(generated).strip()

        except ImportError:
            logger.error("transformers not installed. Run 'pip install transformers'.")
            return self._medgemma_api(prompt)   # fall back to API
        except Exception as e:
            logger.error(f"MedGemma local inference error: {e}")
            return "Unable to generate MedGemma response locally."

    def _medgemma_api(self, prompt: str) -> str:
        """MedGemma via HuggingFace Serverless Inference API."""
        if not self.hf_api_key:
            logger.warning("HF_API_KEY not set — cannot call MedGemma via API.")
            return "MedGemma API key not configured. Set HF_API_KEY in your .env file."

        # The serverless API uses the chat-completion endpoint for instruction-tuned models
        url = f"https://api-inference.huggingface.co/models/{self.medgemma_model}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.hf_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.medgemma_model,
            "messages": [
                {"role": "system", "content": _MEDGEMMA_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 512,
            "temperature": 0.4,
            "top_p": 0.9,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            logger.error(f"MedGemma API error {resp.status_code}: {resp.text[:300]}")
            return "MedGemma API returned an error. Check HF_API_KEY and model access."
        except requests.exceptions.Timeout:
            logger.error("MedGemma API timed out.")
            return "MedGemma API request timed out. Try again later."
        except Exception as e:
            logger.error(f"MedGemma API request failed: {e}")
            return "Unable to reach MedGemma API."