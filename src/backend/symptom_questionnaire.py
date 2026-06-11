# src/backend/symptom_questionnaire.py

import pandas as pd
import numpy as np
import json
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SymptomQuestionnaire:
    """Class for managing interactive symptom questionnaires"""
    
    def __init__(self, data_path):
        """
        Initialize the questionnaire with medical data
        
        Args:
            data_path (str): Path to the medical data CSV file
        """
        try:
            self.medical_data = pd.read_csv(data_path)
            logger.info(f"Loaded medical data with {len(self.medical_data)} entries")
            
            # Extract all symptoms from the dataset
            self.all_symptoms = self._extract_all_symptoms()
            logger.info(f"Extracted {len(self.all_symptoms)} unique symptoms")
            
            # Common initial symptoms to ask about
            self.initial_symptoms = [
                "Fever", "Headache", "Cough", "Fatigue", 
                "Shortness of breath", "Nausea", "Chest pain",
                "Abdominal pain", "Muscle pain", "Joint pain", 
                "Skin rash", "Sore throat", "Sneezing", "Runny nose"
            ]
            
        except Exception as e:
            logger.error(f"Error initializing SymptomQuestionnaire: {e}")
            # Create empty datasets as fallback
            self.medical_data = pd.DataFrame()
            self.all_symptoms = []
            self.initial_symptoms = []
    
    def _extract_all_symptoms(self):
        """Extract all unique symptoms from the medical dataset"""
        symptoms = set()
        
        for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
            if col in self.medical_data.columns:
                symptoms.update(self.medical_data[col].dropna().unique())
        
        # Remove any empty strings or non-string values
        return [s for s in symptoms if isinstance(s, str) and s.strip()]
    
    def get_initial_questions(self):
        """Get the initial set of symptoms to ask about"""
        if self.initial_symptoms:
            return self.initial_symptoms
        elif self.all_symptoms:
            # If no predefined initial symptoms, use the most common ones from dataset
            return list(self.all_symptoms)[:15]  # Return top 15 symptoms
        else:
            # Fallback if no symptoms are available
            return ["Fever", "Cough", "Headache", "Fatigue", "Pain"]
    
    def get_next_questions(self, confirmed_symptoms, excluded_symptoms=None):
        """
        Get the next set of questions based on previous answers
        
        Args:
            confirmed_symptoms (list): Symptoms that user confirmed
            excluded_symptoms (list): Symptoms that user denied
            
        Returns:
            list: Next symptoms to ask about
        """
        if not confirmed_symptoms:
            return self.get_initial_questions()
            
        excluded_symptoms = excluded_symptoms or []
        
        # Find diseases that match confirmed symptoms
        matching_diseases = self._find_matching_diseases(confirmed_symptoms)
        
        if not matching_diseases:
            # If no matching diseases, return some common symptoms
            return [s for s in self.all_symptoms if s not in confirmed_symptoms 
                   and s not in excluded_symptoms][:10]
        
        # Get symptoms associated with matching diseases
        relevant_symptoms = self._get_symptoms_for_diseases(matching_diseases)
        
        # Filter out symptoms already asked about
        next_symptoms = [s for s in relevant_symptoms if s not in confirmed_symptoms 
                        and s not in excluded_symptoms]
        
        # Return top 10 most relevant symptoms
        return next_symptoms[:10]
    
    def _find_matching_diseases(self, symptoms):
        """Find diseases that match the given symptoms"""
        matching_diseases = []
        
        for _, row in self.medical_data.iterrows():
            # Get symptoms for this disease
            disease_symptoms = [
                row.get('Symptom1', ''),
                row.get('Symptom2', ''),
                row.get('Symptom3', ''),
                row.get('Symptom4', '')
            ]
            disease_symptoms = [s for s in disease_symptoms if isinstance(s, str) and s]
            
            # Count how many confirmed symptoms match this disease
            matches = sum(1 for s in symptoms if s in disease_symptoms)
            
            if matches > 0:
                matching_diseases.append({
                    'disease': row['Disease'],
                    'match_count': matches,
                    'match_percentage': (matches / len(disease_symptoms)) * 100
                })
        
        # Sort by match percentage (highest first)
        return sorted(matching_diseases, key=lambda x: x['match_percentage'], reverse=True)
    
    def _get_symptoms_for_diseases(self, diseases):
        """Get all symptoms associated with a list of diseases"""
        all_symptoms = []
        
        for disease_info in diseases:
            disease_name = disease_info['disease']
            disease_data = self.medical_data[self.medical_data['Disease'] == disease_name]
            
            if not disease_data.empty:
                for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
                    if col in disease_data.columns:
                        symptom = disease_data.iloc[0][col]
                        if isinstance(symptom, str) and symptom.strip():
                            all_symptoms.append(symptom)
        
        # Remove duplicates while preserving order
        unique_symptoms = []
        for s in all_symptoms:
            if s not in unique_symptoms:
                unique_symptoms.append(s)
        
        return unique_symptoms
    
    def get_probable_diseases(self, symptoms, min_symptoms=2):
        """
        Get probable diseases based on symptoms
        
        Args:
            symptoms (list): List of confirmed symptoms
            min_symptoms (int): Minimum number of matching symptoms required
            
        Returns:
            list: Probable diseases with match scores
        """
        if not symptoms or len(symptoms) < min_symptoms:
            return []
            
        diseases = self._find_matching_diseases(symptoms)
        
        # Filter diseases with at least min_symptoms matches
        diseases = [d for d in diseases if d['match_count'] >= min_symptoms]
        
        # Format the results
        return [
            {
                'disease': d['disease'],
                'score': d['match_percentage']
            }
            for d in diseases
        ]