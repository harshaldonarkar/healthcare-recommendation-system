// src/frontend/static/js/questionnaire.js

const SymptomQuestionnaire = {
    init: function() {
        this.sessionId = null;
        this.currentStep = 0;
        this.confirmedSymptoms = [];
        this.excludedSymptoms = [];
        this.bindEvents();
    },

    bindEvents: function() {
        document.getElementById('start-questionnaire').addEventListener('click', () => this.startQuestionnaire());
        document.getElementById('symptom-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitSymptoms();
        });
    },

    startQuestionnaire: function() {
        // Show loading state
        document.getElementById('questionnaire-container').innerHTML = `
            <div class="text-center py-8">
                <div class="animate-spin inline-block mb-4">
                    <i class="fas fa-spinner text-3xl text-primary"></i>
                </div>
                <p class="text-muted">Loading questionnaire...</p>
            </div>
        `;

        // Start a new questionnaire session
        fetch('/questionnaire/start')
            .then(response => response.json())
            .then(data => {
                this.sessionId = data.session_id;
                this.currentStep = data.step;
                this.renderQuestions(data.questions, data.message);
            })
            .catch(error => {
                console.error('Error starting questionnaire:', error);
                document.getElementById('questionnaire-container').innerHTML = `
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle me-2"></i>
                        <div>Error loading questionnaire. Please try again.</div>
                    </div>
                `;
            });
    },

    renderQuestions: function(questions, message) {
        const container = document.getElementById('questionnaire-container');

        let html = `
            <div class="card shadow-lg mb-6">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0">Step ${this.currentStep} of 5</h4>
                </div>
                <div class="card-body">
                    <p class="text-lg font-semibold mb-6">${message}</p>
                    <form id="symptom-form">
                        <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-6);">
        `;

        // Render each question as a checkbox
        questions.forEach(symptom => {
            html += `
                <div class="form-checkbox">
                    <input class="form-checkbox" type="checkbox" name="symptom" value="${symptom}" id="symptom-${symptom.replace(/\s+/g, '-')}">
                    <label for="symptom-${symptom.replace(/\s+/g, '-')}">
                        ${symptom}
                    </label>
                </div>
            `;
        });

        html += `
                        </div>
                        <div class="flex justify-between gap-4 mt-8">
                            <button type="button" class="btn btn-outline" id="none-apply">
                                <i class="fas fa-times me-2"></i>None Apply
                            </button>
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-arrow-right me-2"></i>Continue
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        `;

        // If we have confirmed symptoms, show them
        if (this.confirmedSymptoms.length > 0) {
            html += `
                <div class="card shadow-lg mb-6">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0"><i class="fas fa-check-circle me-2"></i>Confirmed Symptoms</h5>
                    </div>
                    <div class="card-body">
                        <div class="flex flex-wrap gap-2">
                            ${this.confirmedSymptoms.map(s =>
                                `<span class="badge badge-success"><i class="fas fa-check me-1"></i>${s}</span>`
                            ).join('')}
                        </div>
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;

        // Bind the form submission and "None Apply" button
        document.getElementById('symptom-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitSymptoms();
        });

        document.getElementById('none-apply').addEventListener('click', () => {
            this.excludedSymptoms = [...this.excludedSymptoms, ...questions];
            this.submitSymptoms();
        });
    },

    submitSymptoms: function() {
        // Get selected symptoms
        const confirmed = [];
        document.querySelectorAll('input[name="symptom"]:checked').forEach(input => {
            confirmed.push(input.value);
        });

        // Update confirmed symptoms
        this.confirmedSymptoms = [...this.confirmedSymptoms, ...confirmed];

        // Get excluded symptoms (all unchecked options)
        const excluded = [];
        document.querySelectorAll('input[name="symptom"]:not(:checked)').forEach(input => {
            excluded.push(input.value);
        });

        // Update excluded symptoms
        this.excludedSymptoms = [...this.excludedSymptoms, ...excluded];

        // Show loading state
        document.getElementById('questionnaire-container').innerHTML = `
            <div class="text-center py-8">
                <div class="animate-spin inline-block mb-4">
                    <i class="fas fa-spinner text-3xl text-primary"></i>
                </div>
                <p class="text-muted">Analyzing your responses...</p>
            </div>
        `;

        // Submit to server
        fetch('/questionnaire/respond', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: this.sessionId,
                confirmed: confirmed,
                excluded: excluded
            }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'complete') {
                this.renderResults(data);
            } else {
                this.currentStep = data.step;
                this.renderQuestions(data.questions, data.message);

                // If we have probable diseases, show them
                if (data.probable_diseases && data.probable_diseases.length > 0) {
                    this.renderPreliminaryResults(data.probable_diseases);
                }
            }
        })
        .catch(error => {
            console.error('Error submitting symptoms:', error);
            document.getElementById('questionnaire-container').innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle me-2"></i>
                    <div>Error processing your responses. Please try again.</div>
                </div>
            `;
        });
    },

    renderPreliminaryResults: function(diseases) {
        const container = document.getElementById('questionnaire-container');
        const resultDiv = document.createElement('div');
        resultDiv.className = 'card shadow-lg mb-6';
        resultDiv.innerHTML = `
            <div class="card-header bg-info text-white">
                <h5 class="mb-0"><i class="fas fa-lightbulb me-2"></i>Preliminary Assessment</h5>
            </div>
            <div class="card-body">
                <p class="mb-4">Based on your symptoms so far, these conditions are being considered:</p>
                <div class="flex flex-col gap-3">
                    ${diseases.slice(0, 3).map(disease => `
                        <div class="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                            <span class="font-medium">${disease.disease}</span>
                            <span class="badge badge-primary"><i class="fas fa-percent me-1"></i>${disease.score.toFixed(1)}% match</span>
                        </div>
                    `).join('')}
                </div>
                <p class="mt-4 text-sm text-muted"><i class="fas fa-info-circle me-1"></i>Continue answering questions for a more accurate assessment.</p>
            </div>
        `;

        container.appendChild(resultDiv);
    },

    renderResults: function(data) {
        const container = document.getElementById('questionnaire-container');

        let html = `
            <!-- Results Card -->
            <div class="card shadow-lg mb-6">
                <div class="card-header bg-success text-white">
                    <h4 class="mb-0"><i class="fas fa-check-circle me-2"></i>Analysis Complete</h4>
                </div>
                <div class="card-body">
                    <p class="text-lg mb-6">${data.message}</p>

                    <!-- Primary Assessment -->
                    <h5 class="text-xl font-bold mb-4"><i class="fas fa-star-half-alt me-2 text-warning"></i>Primary Assessment</h5>
                    <div class="alert alert-info mb-6">
                        <h4 class="text-lg font-bold mb-2">${data.predictions[0].disease}</h4>
                        <div class="flex items-center gap-2 mb-3">
                            <div class="progress" style="flex: 1;">
                                <div class="progress-bar" style="width: ${data.predictions[0].score}%;"></div>
                            </div>
                            <span class="font-semibold text-lg">${data.predictions[0].score.toFixed(1)}%</span>
                        </div>
                        <p class="text-sm mt-3"><i class="fas fa-info-circle me-1"></i>This assessment is based on the symptoms you reported. Please consult a healthcare professional for proper diagnosis.</p>
                    </div>

                    <!-- Your Symptoms -->
                    <h5 class="text-lg font-bold mb-3"><i class="fas fa-check me-2 text-success"></i>Your Reported Symptoms</h5>
                    <div class="flex flex-wrap gap-2 mb-6">
                        ${data.confirmed_symptoms.map(s =>
                            `<span class="badge badge-info"><i class="fas fa-check-circle me-1"></i>${s}</span>`
                        ).join('')}
                    </div>

                    <!-- Other Possibilities -->
                    <h5 class="text-lg font-bold mb-3"><i class="fas fa-list me-2"></i>Other Possibilities</h5>
                    <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-6);">
                        ${data.predictions.slice(1).map(prediction => `
                            <div class="card border-1 border-gray-200">
                                <div class="card-header bg-gray-50 flex justify-between items-center">
                                    <span class="font-semibold">${prediction.disease}</span>
                                    <span class="badge badge-secondary">${prediction.score.toFixed(1)}%</span>
                                </div>
                                <div class="card-body">
                                    <p class="text-sm"><strong>Common symptoms:</strong></p>
                                    <p class="text-sm text-muted">${prediction.symptoms.join(', ')}</p>
                                </div>
                            </div>
                        `).join('')}
                    </div>

                    <!-- Actions -->
                    <div class="flex gap-3 mt-6">
                        <a href="/disease-dashboard/${data.predictions[0].disease}" class="btn btn-success flex-1">
                            <i class="fas fa-chart-bar me-2"></i>View Detailed Dashboard
                        </a>
                        <button class="btn btn-outline flex-1" id="restart-questionnaire">
                            <i class="fas fa-redo me-2"></i>Start Over
                        </button>
                    </div>
                </div>
            </div>

            <!-- Recommendations Card -->
            <div class="card shadow-lg mb-6">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="fas fa-lightbulb me-2"></i>Recommendations</h4>
                </div>
                <div class="card-body">
                    <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: var(--space-6);">
                        <div>
                            <h5 class="font-bold mb-4"><i class="fas fa-shield-heart me-2 text-success"></i>Care Guidelines</h5>
                            <ul class="flex flex-col gap-2">
                                ${data.recommendations.precautions.map(p =>
                                    `<li class="flex items-start gap-2"><i class="fas fa-check-circle text-success mt-1"></i><span>${p}</span></li>`
                                ).join('')}
                            </ul>
                        </div>
                        <div>
                            <h5 class="font-bold mb-4"><i class="fas fa-apple-alt me-2 text-info"></i>Dietary Recommendations</h5>
                            <p class="text-sm leading-relaxed mb-4">${data.recommendations.diet}</p>

                            <h5 class="font-bold mb-4 mt-4"><i class="fas fa-running me-2 text-warning"></i>Exercise Guidance</h5>
                            <p class="text-sm leading-relaxed">${data.recommendations.workout}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Final Disclaimer -->
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>
                <div>
                    <strong>Important Disclaimer:</strong> This is not a medical diagnosis. Please consult with a qualified healthcare provider for proper diagnosis and treatment. Seek immediate medical attention if you experience severe symptoms.
                </div>
            </div>
        `;

        container.innerHTML = html;

        // Bind the restart button
        document.getElementById('restart-questionnaire').addEventListener('click', () => {
            this.init();
            this.startQuestionnaire();
        });
    }
};

// Initialize the questionnaire when the page loads
document.addEventListener('DOMContentLoaded', function() {
    SymptomQuestionnaire.init();
});
