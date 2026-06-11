# src/backend/llm_integration.py

import requests
import json
import os
from typing import Dict, List, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMIntegration:
    """Class to handle LLM integration for enhanced healthcare recommendations"""
    
    def __init__(self, llm_provider="groq"):
        """
        Initialize the LLM integration
        
        Args:
            llm_provider (str): The LLM provider to use ("huggingface", "ollama", or "openai" or "groq")
        """
        self.llm_provider = llm_provider
        
        # Hugging Face settings
        self.hf_api_url = "https://api-inference.huggingface.co/models"
        self.hf_model = os.environ.get("HF_MODEL", "google/flan-t5-large")  # A good free model for medical text
        self.hf_api_key = os.environ.get("HF_API_KEY", "")  # Get API key from environment
        
        # Ollama settings (if self-hosted)
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.ollama_model = os.environ.get("OLLAMA_MODEL", "mistral")  # or "llama2" or any model you've pulled
        
        # OpenAI settings
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
        
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.groq_model = os.environ.get("GROQ_MODEL", "mixtral-8x7b-32768")
        
        logger.info(f"LLM integration initialized with provider: {llm_provider}")
    
    def enhance_disease_detection(self, symptoms: str, bert_predictions: List[Dict]) -> List[Dict]:
        """
        Use LLM to analyze symptoms in natural language and enhance BERT predictions
        
        Args:
            symptoms (str): User's symptom description
            bert_predictions (List[Dict]): BERT model predictions with confidence scores
            
        Returns:
            List[Dict]: Enhanced predictions with LLM analysis
        """
        # Create a prompt for the LLM
        diseases = [p["disease"] for p in bert_predictions]
        confidence_scores = [f"{p['disease']}: {p['confidence']:.1f}%" for p in bert_predictions]
        
        prompt = f"""
        Patient symptoms: "{symptoms}"
        
        BERT model predicted these diseases with confidence scores:
        {', '.join(confidence_scores)}
        
        Based on medical knowledge and these symptoms, analyze if these predictions are reasonable.
        Provide a brief analysis of why each disease might match these symptoms.
        Also, suggest if any other conditions should be considered.
        Keep your response concise and focused on medical analysis.
        """
        
        # Get LLM response
        llm_analysis = self._get_llm_response(prompt)
        
        # Add LLM analysis to predictions
        enhanced_predictions = bert_predictions.copy()
        for prediction in enhanced_predictions:
            # Extract relevant analysis for this disease
            disease_name = prediction["disease"]
            # Simple extraction strategy - find paragraphs mentioning the disease
            paragraphs = [p for p in llm_analysis.split("\n\n") if disease_name in p]
            analysis = "\n".join(paragraphs) if paragraphs else ""
            
            # Add LLM analysis to prediction
            prediction["llm_analysis"] = analysis
            
        return enhanced_predictions
    
    def generate_personalized_recommendations(
        self, 
        disease: str, 
        basic_recommendations: Dict[str, Any], 
        user_profile: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Generate personalized recommendations using LLM based on disease and user profile
        
        Args:
            disease (str): Predicted disease
            basic_recommendations (Dict): Basic recommendations from database
            user_profile (Dict): User profile with allergies, conditions, etc.
            
        Returns:
            Dict: Enhanced personalized recommendations
        """
        # Extract user profile information
        allergies = user_profile.get("allergies", []) if user_profile else []
        conditions = user_profile.get("conditions", []) if user_profile else []
        age = user_profile.get("age", "unknown") if user_profile else "unknown"
        gender = user_profile.get("gender", "unknown") if user_profile else "unknown"
        
        # Create a prompt for the LLM
        prompt = f"""
        Based on a diagnosis of {disease}, I need personalized healthcare recommendations.
        
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
        
        Please provide personalized recommendations taking into account the patient profile.
        Focus on:
        1. Any medication considerations (allergies, interactions with conditions)
        2. Diet adjustments based on their profile
        3. Exercise modifications if needed
        4. Additional precautions
        
        Keep your response structured and concise.
        """
        
        # Get LLM response
        personalized_advice = self._get_llm_response(prompt)
        
        # Add personalized recommendations to the basic ones
        enhanced_recommendations = basic_recommendations.copy()
        enhanced_recommendations["personalized_advice"] = personalized_advice
        
        return enhanced_recommendations
    
    def explain_in_simple_terms(self, disease: str, medical_info: str) -> str:
        """
        Use LLM to explain medical information in simpler terms for patients
        """
        try:
            # Your existing LLM code here
            prompt = f"""
            Please explain the following medical information about {disease} in simple, 
            non-technical language that a patient could easily understand:
            
            {medical_info}
            
            Keep the explanation conversational, reassuring, and easy to understand.
            """
            
            explanation = self._get_llm_response(prompt)
            if explanation and "error" not in explanation.lower():
                return explanation
                
            # If we get here, the LLM failed or returned an error
            raise Exception("LLM provided an error response")
            
        except Exception as e:
            logger.error(f"Error generating explanation: {e}")
            
            # Provide a basic explanation even when the LLM fails
            return f"{disease} is a condition that may cause symptoms such as {medical_info.split('Common symptoms include')[1] if 'Common symptoms include' in medical_info else 'the symptoms you described'}. It's typically caused by {medical_info.split('.')[0] if '.' in medical_info else 'various factors'}. Please consult with a healthcare professional for a proper diagnosis and treatment plan."
    # Add this to _get_llm_response in llm_integration.py
    def _get_llm_response(self, prompt: str) -> str:
        """Get response from selected LLM provider"""
        try:
            logger.info(f"Attempting to get response from {self.llm_provider}")
            
            if self.llm_provider == "huggingface":
                logger.info(f"HF API key available: {'Yes' if self.hf_api_key else 'No'}")
                logger.info(f"HF model: {self.hf_model}")
                return self._get_huggingface_response(prompt)
            elif self.llm_provider == "ollama":
                return self._get_ollama_response(prompt)
            elif self.llm_provider == "openai":
                return self._get_openai_response(prompt)
            elif self.llm_provider == "groq":
                return self._get_groq_response(prompt)
            else:
                raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")
        except Exception as e:
            logger.error(f"Error getting LLM response: {e}")
            return f"Error generating enhanced recommendations. Please rely on the basic recommendations provided."
    def _get_huggingface_response(self, prompt: str) -> str:
      """Get response from Hugging Face Inference API"""
      try:
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
              # Provide a fallback response
              return "Unable to generate enhanced explanation. The basic prediction is based on symptom analysis."
      except Exception as e:
          logger.error(f"Hugging Face API error: {e}")
    def _get_ollama_response(self, prompt: str) -> str:
        """Get response from Ollama self-hosted API"""
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        response = requests.post(
            self.ollama_url,
            json=payload
        )
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            logger.error(f"Ollama API error: {response.text}")
            return "Unable to generate enhanced recommendations."
    
    def _get_openai_response(self, prompt: str) -> str:
        """Get response from OpenAI API"""
        try:
            import openai
            openai.api_key = self.openai_api_key
            
            response = openai.ChatCompletion.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are a medical assistant providing helpful, accurate, and concise healthcare information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message["content"]
        except ImportError:
            logger.error("OpenAI package not installed. Run 'pip install openai' to use OpenAI.")
            return "OpenAI integration unavailable. Please install the openai package."
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return "Unable to generate enhanced recommendations."
        
    def _get_groq_response(self, prompt: str) -> str:
        """Get response from Groq API"""
        try:
            import groq
            
            # Initialize Groq client
            client = groq.Client(api_key=self.groq_api_key)
            
            response = client.chat.completions.create(
                model=self.groq_model,
                messages=[
                    {"role": "system", "content": "You are a medical assistant providing helpful, accurate, and concise healthcare information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message.content
        except ImportError:
            logger.error("Groq package not installed. Run 'pip install groq' to use Groq.")
            return "Groq integration unavailable. Please install the groq package."
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return "Unable to generate enhanced recommendations."