# src/backend/symptom_analysis.py

import pandas as pd
import re
import random
from collections import Counter
import logging

logger = logging.getLogger(__name__)

class SymptomAnalyzer:
    """
    Class for analyzing symptoms and generating interactive follow-up questions
    """
    
    def __init__(self, data_path, llm_integration=None):
        """
        Initialize the symptom analyzer with medical data
        
        Args:
            data_path (str): Path to the medical data CSV file
            llm_integration: Optional LLM integration for enhanced analysis
        """
        try:
            self.data = pd.read_csv(data_path)
            logger.info(f"Loaded medical data with {len(self.data)} records")
            
            # Store the LLM integration if provided
            self.llm = llm_integration
            
            # Extract all unique symptoms
            self.all_symptoms = set()
            for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
                symptoms = self.data[col].dropna().unique()
                self.all_symptoms.update(symptoms)
                
            # Create lowercase version of symptoms for matching
            self.symptoms_lower = {s.lower(): s for s in self.all_symptoms if isinstance(s, str)}
            
            # Create symptom synonyms for better matching
            self.symptom_synonyms = {
                'headache': ['head pain', 'head ache', 'migraine'],
                'fever': ['high temperature', 'elevated temperature', 'hot'],
                'cough': ['coughing', 'hacking'],
                'fatigue': ['tired', 'exhaustion', 'tiredness', 'low energy'],
                'nausea': ['feeling sick', 'queasy', 'upset stomach'],
                'sore throat': ['throat pain', 'painful throat', 'scratchy throat'],
                'dizziness': ['vertigo', 'lightheaded', 'feeling faint'],
                'chest pain': ['chest discomfort', 'chest tightness'],
                'shortness of breath': ['difficulty breathing', 'can\'t breathe', 'breathlessness'],
                'muscle pain': ['myalgia', 'sore muscles', 'muscle ache']
            }
            
            # Precompute symptom-to-disease mapping for faster lookups
            self.symptom_to_diseases = {}
            for _, row in self.data.iterrows():
                disease = row['Disease']
                for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
                    if pd.notna(row[col]) and row[col]:
                        symptom = row[col]
                        if symptom not in self.symptom_to_diseases:
                            self.symptom_to_diseases[symptom] = []
                        self.symptom_to_diseases[symptom].append(disease)
        
        except Exception as e:
            logger.error(f"Error initializing SymptomAnalyzer: {e}")
            self.data = None
            self.all_symptoms = set()
            self.symptoms_lower = {}
            self.symptom_synonyms = {}
            self.symptom_to_diseases = {}
    
    def analyze_symptom_patterns(self, symptoms_text):
        """
        Analyze symptom text to extract patterns and predict potential conditions
        
        Args:
            symptoms_text (str): Text describing symptoms
            
        Returns:
            dict: Analysis results including detected symptoms and potential matches
        """
        try:
            # Normalize the text
            normalized_text = symptoms_text.lower()
            
            # Extract symptoms using various methods
            detected_symptoms = self._extract_symptoms(normalized_text)
            
            # Get potential disease matches based on symptoms
            potential_matches = self._get_potential_matches(detected_symptoms)
            
            # Prepare the response
            return {
                'detected_symptoms': detected_symptoms,
                'potential_matches': potential_matches,
                'message': f"Detected {len(detected_symptoms)} symptoms that match our database."
            }
            
        except Exception as e:
            logger.error(f"Error in analyze_symptom_patterns: {e}")
            return {
                'detected_symptoms': [],
                'potential_matches': [],
                'message': "Error analyzing symptoms."
            }
    
    def _extract_symptoms(self, text):
        """
        Extract symptoms from text using multiple approaches
        
        Args:
            text (str): Normalized (lowercase) symptom text
            
        Returns:
            list: Detected symptoms
        """
        detected = set()
        
        # Direct symptom matching
        for symptom_lower, original_symptom in self.symptoms_lower.items():
            if symptom_lower in text:
                detected.add(original_symptom)
        
        # Synonym matching
        for symptom, synonyms in self.symptom_synonyms.items():
            if symptom in text:
                original = self.symptoms_lower.get(symptom, symptom)
                detected.add(original)
            else:
                for synonym in synonyms:
                    if synonym in text:
                        original = self.symptoms_lower.get(symptom, symptom)
                        detected.add(original)
                        break
        
        # Pattern matching for common symptom descriptions
        patterns = [
            (r'(pain|ache) in (my )?(head|neck|chest|stomach|abdomen|back|joints)', r'\1 in \3'),
            (r'(sore|painful) (throat|muscles|joints|lymph nodes|chest)', r'\1 \2'),
            (r'(having|have|experiencing|feel|feeling) (a )?(bad |severe )?(headache|fever|cough|fatigue|nausea)', r'\4'),
            (r'(can\'?t|difficulty|trouble) (breathing|sleeping|eating)', r'difficulty \2'),
            (r'(runny|stuffy|blocked) nose', 'nasal congestion')
        ]
        
        for pattern, replacement in patterns:
            matches = re.findall(pattern, text)
            if matches:
                replacement_text = re.sub(pattern, replacement, text)
                parts = replacement_text.split()
                for i in range(len(parts)-1):
                    potential_symptom = f"{parts[i]} {parts[i+1]}"
                    if potential_symptom in self.symptoms_lower:
                        original = self.symptoms_lower.get(potential_symptom, potential_symptom)
                        detected.add(original)
        
        # If LLM integration is available, use it for better extraction
        if self.llm:
            try:
                llm_symptoms = self.llm.extract_symptoms(text)
                for symptom in llm_symptoms:
                    if symptom.lower() in self.symptoms_lower:
                        original = self.symptoms_lower.get(symptom.lower(), symptom)
                        detected.add(original)
            except Exception as e:
                logger.error(f"Error using LLM for symptom extraction: {e}")
        
        # If still no symptoms detected, check for general terms
        if not detected and any(term in text for term in ['sick', 'ill', 'unwell', 'not feeling well']):
            detected.add('Fatigue')
        
        return list(detected)
    
    def _get_potential_matches(self, symptoms):
        """
        Get potential disease matches based on detected symptoms
        
        Args:
            symptoms (list): Detected symptoms
            
        Returns:
            list: Potential disease matches with scores
        """
        if not symptoms:
            return []
            
        # Count symptom occurrences for each disease
        disease_scores = {}
        
        for symptom in symptoms:
            if symptom in self.symptom_to_diseases:
                for disease in self.symptom_to_diseases[symptom]:
                    if disease not in disease_scores:
                        disease_scores[disease] = {
                            'count': 0, 
                            'total_symptoms': 0,
                            'specificity': 0
                        }
                    
                    disease_scores[disease]['count'] += 1
                    
                    # Calculate specificity bonus
                    diseases_with_symptom = len(self.symptom_to_diseases[symptom])
                    if diseases_with_symptom <= 3:
                        disease_scores[disease]['specificity'] += 15
                    elif diseases_with_symptom <= 6:
                        disease_scores[disease]['specificity'] += 10
                    elif diseases_with_symptom <= 10:
                        disease_scores[disease]['specificity'] += 5
        
        # Calculate total symptoms for each disease
        for disease in disease_scores:
            disease_data = self.data[self.data['Disease'] == disease]
            if not disease_data.empty:
                row = disease_data.iloc[0]
                total = 0
                for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
                    if pd.notna(row[col]) and row[col]:
                        total += 1
                disease_scores[disease]['total_symptoms'] = max(1, total)  # Avoid division by zero
        
        # Calculate final scores
        results = []
        for disease, scores in disease_scores.items():
            # Base score is percentage of symptoms matched
            base_score = (scores['count'] / scores['total_symptoms']) * 100
            
            # Add specificity bonus but cap at 100%
            final_score = min(base_score + scores['specificity'], 100)
            
            results.append({
                'disease': disease,
                'score': final_score,
                'matched_symptoms': scores['count'],
                'total_symptoms': scores['total_symptoms']
            })
        
        # Sort by score and return top matches
        return sorted(results, key=lambda x: x['score'], reverse=True)
    
    def _generate_followup_questions(self, symptoms_text, detected_symptoms, primary_condition=None):
        """
        Generate follow-up questions based on current input and detected symptoms
        
        Args:
            symptoms_text (str): Original symptom text
            detected_symptoms (list): Already detected symptoms
            primary_condition (str): Primary suspected condition, if any
            
        Returns:
            list: Follow-up questions to ask
        """
        followup_questions = []
        text_lower = symptoms_text.lower()
        
        # Ask about duration if not mentioned
        if not any(term in text_lower for term in ['day', 'week', 'month', 'hour', 'since', 'started']):
            followup_questions.append("How long have you been experiencing these symptoms?")
        
        # Ask about severity if not mentioned
        if not any(term in text_lower for term in ['severe', 'mild', 'moderate', 'intensity', 'bad', 'awful', 'terrible']):
            followup_questions.append("How severe are your symptoms on a scale from 1 to 10?")
        
        # If primary condition is known, ask about related symptoms
        if primary_condition:
            # Get symptoms associated with the primary condition
            condition_data = self.data[self.data['Disease'] == primary_condition]
            if not condition_data.empty:
                condition_symptoms = []
                row = condition_data.iloc[0]
                for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
                    if pd.notna(row[col]) and row[col] and row[col] not in detected_symptoms:
                        condition_symptoms.append(row[col])
                
                # Add questions about specific symptoms for this condition
                for symptom in condition_symptoms:
                    followup_questions.append(f"Are you experiencing {symptom}?")
        
        # Add general follow-up questions based on body systems not yet covered
        body_systems = {
            'respiratory': ['cough', 'shortness of breath', 'wheezing', 'chest tightness'],
            'gastrointestinal': ['nausea', 'vomiting', 'diarrhea', 'constipation', 'abdominal pain'],
            'neurological': ['headache', 'dizziness', 'confusion', 'fainting', 'seizures'],
            'musculoskeletal': ['joint pain', 'muscle pain', 'weakness', 'stiffness']
        }
        
        # Check which body systems are already covered by detected symptoms
        detected_lower = [s.lower() for s in detected_symptoms]
        covered_systems = set()
        
        for system, system_symptoms in body_systems.items():
            if any(s in detected_lower for s in system_symptoms):
                covered_systems.add(system)
        
        # Ask about systems not yet covered
        for system, system_symptoms in body_systems.items():
            if system not in covered_systems:
                sample_symptoms = ', '.join(system_symptoms[:3])
                followup_questions.append(f"Do you have any {system} symptoms such as {sample_symptoms}?")
        
        # Limit to a reasonable number of questions
        return followup_questions[:3]
    
    def generate_detailed_analysis(self, symptoms_text, predictions):
        """
        Generate a detailed analysis of symptoms with explanations
        
        Args:
            symptoms_text (str): Text describing symptoms
            predictions (list): Disease predictions with confidence scores
            
        Returns:
            dict: Detailed analysis
        """
        try:
            # Extract symptoms
            analysis_results = self.analyze_symptom_patterns(symptoms_text)
            detected_symptoms = analysis_results['detected_symptoms']
            
            # Get the primary predicted disease (if any)
            primary_disease = predictions[0]['disease'] if predictions else None
            
            # Get recommendations for the primary disease
            recommendations = {}
            if primary_disease:
                disease_data = self.data[self.data['Disease'] == primary_disease]
                if not disease_data.empty:
                    row = disease_data.iloc[0]
                    recommendations = {
                        'precautions': [
                            row['Precaution1'] if pd.notna(row['Precaution1']) else '',
                            row['Precaution2'] if pd.notna(row['Precaution2']) else '',
                            row['Precaution3'] if pd.notna(row['Precaution3']) else '',
                            row['Precaution4'] if pd.notna(row['Precaution4']) else ''
                        ],
                        'diet': row['Diets'] if pd.notna(row['Diets']) else 'Maintain a balanced diet',
                        'recommended_actions': self._generate_recommended_actions(primary_disease, detected_symptoms)
                    }
            
            # Generate symptom explanations
            symptom_explanations = {}
            for symptom in detected_symptoms:
                if self.llm:
                    try:
                        explanation = self.llm.explain_symptom(symptom)
                        symptom_explanations[symptom] = explanation
                    except:
                        symptom_explanations[symptom] = f"Common symptom that may indicate various conditions."
                else:
                    # Generate simple explanations without LLM
                    related_diseases = self.symptom_to_diseases.get(symptom, [])
                    if len(related_diseases) <= 3:
                        symptom_explanations[symptom] = f"Specific symptom commonly associated with {', '.join(related_diseases)}."
                    else:
                        symptom_explanations[symptom] = f"Common symptom that may indicate various conditions."
            
            # Combine everything into a detailed analysis
            return {
                'detected_symptoms': detected_symptoms,
                'symptom_explanations': symptom_explanations,
                'primary_assessment': primary_disease,
                'recommendations': recommendations,
                'followup_questions': self._generate_followup_questions(symptoms_text, detected_symptoms, primary_disease),
                'detailed_explanation': self._generate_detailed_explanation(symptoms_text, detected_symptoms, predictions)
            }
            
        except Exception as e:
            logger.error(f"Error in generate_detailed_analysis: {e}")
            return {
                'detected_symptoms': [],
                'symptom_explanations': {},
                'primary_assessment': None,
                'recommendations': {},
                'followup_questions': ["Could you provide more details about your symptoms?"],
                'detailed_explanation': "Unable to generate a detailed analysis due to an error."
            }
    
    def _generate_recommended_actions(self, disease, symptoms):
        """
        Generate recommended actions based on the disease and symptoms
        
        Args:
            disease (str): Predicted disease
            symptoms (list): Detected symptoms
            
        Returns:
            list: Recommended actions
        """
        actions = ["Consult with a healthcare professional for proper diagnosis"]
        
        # Add symptom-specific recommendations
        urgent_symptoms = [
            'Chest pain', 'Shortness of breath', 'High fever', 'Severe headache',
            'Sudden confusion', 'Fainting', 'Seizures'
        ]
        
        if any(s in symptoms for s in urgent_symptoms):
            actions.insert(0, "Seek immediate medical attention")
        
        # Add disease-specific recommendations
        if disease in ['Common Cold', 'Flu', 'Viral Fever']:
            actions.append("Rest and stay hydrated")
            actions.append("Monitor your symptoms and avoid strenuous activities")
            
        elif disease in ['Migraine', 'Tension Headache']:
            actions.append("Rest in a quiet, dark room")
            actions.append("Apply cold or warm compresses to your head or neck")
        
        elif disease in ['Food Poisoning', 'Gastroenteritis']:
            actions.append("Stay hydrated with water and electrolyte solutions")
            actions.append("Avoid solid foods until symptoms improve")
        
        # Generic recommendations
        actions.append("Follow a balanced diet and get adequate rest")
        
        return actions
    
    def _generate_detailed_explanation(self, symptoms_text, detected_symptoms, predictions):
        """
        Generate a detailed explanation of the symptom analysis
        
        Args:
            symptoms_text (str): Original symptom text
            detected_symptoms (list): Detected symptoms
            predictions (list): Disease predictions with confidence scores
            
        Returns:
            str: Detailed explanation
        """
        if self.llm:
            try:
                # Use LLM for a comprehensive explanation
                primary_disease = predictions[0]['disease'] if predictions else None
                return self.llm.generate_symptom_analysis(symptoms_text, detected_symptoms, primary_disease)
            except Exception as e:
                logger.error(f"Error generating LLM explanation: {e}")
        
        # Fallback to template-based explanation
        if not predictions:
            return "Based on the symptoms you've described, I couldn't make a clear determination. Please provide more detailed information about your symptoms."
        
        primary = predictions[0]
        confidence_level = "high" if primary['score'] > 80 else "moderate" if primary['score'] > 60 else "possible"
        
        explanation = f"Based on your reported symptoms ({', '.join(detected_symptoms)}), there's a {confidence_level} possibility of {primary['disease']}. "
        
        if len(predictions) > 1:
            explanation += f"Other possibilities include {predictions[1]['disease']} and {predictions[2]['disease'] if len(predictions) > 2 else 'other conditions'}. "
        
        explanation += "Remember that this is not a medical diagnosis. Consult with a healthcare professional for proper evaluation and treatment."
        
        return explanation