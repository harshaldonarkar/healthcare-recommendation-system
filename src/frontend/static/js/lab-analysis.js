
document.addEventListener('DOMContentLoaded', function() {
    initializeLabAnalysis();
});

function initializeLabAnalysis() {
    setupFileUpload();
    setupManualEntry();
    
    // Only try to load history if we're on that tab
    const historyTab = document.getElementById('history-tab');
    if (historyTab) {
        historyTab.addEventListener('shown.bs.tab', function() {
            loadLabHistory();
        });
    }

    // Only try to load available tests if on relevant tab
    const manualTab = document.getElementById('manual-tab');
    if (manualTab) {
        manualTab.addEventListener('shown.bs.tab', function() {
            loadAvailableTests();
        });
    }
}

function setupFileUpload() {
    const fileInput = document.getElementById('labReportFile');
    const uploadArea = document.getElementById('uploadArea');
    
    if (!fileInput || !uploadArea) {
        console.error('File upload elements not found');
        return;
    }
    
    // Handle drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('border-primary', 'bg-light');
    });
    
    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('border-primary', 'bg-light');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('border-primary', 'bg-light');
        
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handleFileUpload(e.target.files[0]);
        }
    });
}

function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('csrf_token', getCsrfToken());

    const progressBar = document.getElementById('uploadProgress');
    const progressBarInner = document.getElementById('progressBar');

    if (progressBar) progressBar.style.display = 'block';
    if (progressBarInner) progressBarInner.style.width = '0%';

    const resultsContainer = document.getElementById('uploadResults');
    if (resultsContainer) {
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = `
            <div class="alert alert-info" style="display:flex;align-items:center;gap:10px;">
                <span class="loading-spinner" style="width:18px;height:18px;border-width:2px;" aria-hidden="true"></span>
                <span>Processing your lab report — please wait…</span>
            </div>
        `;
    }

    fetch('/lab-analysis/upload', {
        method: 'POST',
        body: formData,
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        return response.json();
    })
    .then(data => {
        if (progressBarInner) progressBarInner.style.width = '100%';
        setTimeout(() => {
            if (progressBar) progressBar.style.display = 'none';
            displayUploadResults(data);
        }, 400);
    })
    .catch(error => {
        console.error('Error:', error);
        if (progressBar) progressBar.style.display = 'none';
        showError('Failed to upload lab report: ' + error.message);
    });
}

function displayUploadResults(data) {
    const resultsContainer = document.getElementById('uploadResults');
    if (!resultsContainer) {
        console.error('Results container not found');
        return;
    }
    
    resultsContainer.style.display = 'block';
    
    let html = '';
    
    if (data.status === 'success' && data.analysis) {
        html = generateAnalysisResults(data.analysis);
    } else {
        html = `
            <div class="alert alert-warning">
                ${data.message || 'Could not process lab report'}
            </div>
        `;
    }
    
    resultsContainer.innerHTML = html;
}

function setupManualEntry() {
    // Initialize with one test entry
    updateRemoveButtons();
    
    // Set up add test button
    const addTestBtn = document.querySelector('button[onclick="addTestEntry()"]');
    if (addTestBtn) {
        // Replace the inline handler with addEventListener
        addTestBtn.removeAttribute('onclick');
        addTestBtn.addEventListener('click', addTestEntry);
    }
    
    // Set up submit button
    const submitBtn = document.querySelector('button[onclick="submitManualEntry()"]');
    if (submitBtn) {
        // Replace the inline handler with addEventListener
        submitBtn.removeAttribute('onclick');
        submitBtn.addEventListener('click', submitManualEntry);
    }
}

function addTestEntry() {
    const form = document.getElementById('manualEntryForm');
    if (!form) {
        showError('Manual entry form not found');
        return;
    }
    
    const testEntry = document.createElement('div');
    testEntry.className = 'test-entry mb-3';
    testEntry.innerHTML = `
        <div class="row g-3">
            <div class="col-md-4">
                <select class="form-select test-name" required>
                    <option value="">Select Test</option>
                    <option value="blood_glucose_fasting">Blood Glucose (Fasting)</option>
                    <option value="hba1c">HbA1c</option>
                    <option value="total_cholesterol">Total Cholesterol</option>
                    <option value="ldl_cholesterol">LDL Cholesterol</option>
                    <option value="hdl_cholesterol">HDL Cholesterol</option>
                    <option value="triglycerides">Triglycerides</option>
                    <option value="hemoglobin">Hemoglobin</option>
                    <option value="wbc_count">WBC Count</option>
                    <option value="platelet_count">Platelet Count</option>
                    <option value="creatinine">Creatinine</option>
                    <option value="alt_sgpt">ALT/SGPT</option>
                    <option value="ast_sgot">AST/SGOT</option>
                    <option value="thyroid_tsh">TSH</option>
                    <option value="vitamin_d">Vitamin D</option>
                    <option value="vitamin_b12">Vitamin B12</option>
                </select>
            </div>
            <div class="col-md-3">
                <input type="number" class="form-control test-value" placeholder="Value" required>
            </div>
            <div class="col-md-2">
                <input type="text" class="form-control test-unit" placeholder="Unit">
            </div>
            <div class="col-md-3">
                <button class="btn btn-danger remove-test" type="button">
                    <i class="fas fa-trash"></i> Remove
                </button>
            </div>
        </div>
    `;
    
    // Set up remove button click handler
    const removeBtn = testEntry.querySelector('.remove-test');
    if (removeBtn) {
        removeBtn.addEventListener('click', function() {
            removeTestEntry(this);
        });
    }
    
    form.appendChild(testEntry);
    updateRemoveButtons();
}

function removeTestEntry(button) {
    const testEntry = button.closest('.test-entry');
    if (testEntry) {
        testEntry.remove();
        updateRemoveButtons();
    }
}

function updateRemoveButtons() {
    const testEntries = document.querySelectorAll('.test-entry');
    testEntries.forEach((entry, index) => {
        const removeButton = entry.querySelector('.remove-test');
        if (removeButton) {
            if (testEntries.length === 1) {
                removeButton.style.display = 'none';
            } else {
                removeButton.style.display = 'inline-block';
            }
        }
    });
}

function submitManualEntry() {
    const testEntries = document.querySelectorAll('.test-entry');
    const labResults = [];
    
    testEntries.forEach(entry => {
        const testName = entry.querySelector('.test-name')?.value;
        const testValue = entry.querySelector('.test-value')?.value;
        const testUnit = entry.querySelector('.test-unit')?.value;
        
        if (testName && testValue) {
            labResults.push({
                test_name: testName,
                value: parseFloat(testValue),
                unit: testUnit
            });
        }
    });
    
    if (labResults.length === 0) {
        showError('Please enter at least one valid test result');
        return;
    }
    
    fetch('/lab-analysis/manual-entry', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify({ lab_results: labResults }),
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            displayManualEntryResults(data.analysis);
            loadLabHistory(); // Refresh history
        } else {
            showError(data.error || 'Failed to process manual entry');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to submit lab results: ' + error.message);
    });
}

function displayManualEntryResults(analysis) {
    const resultsContainer = document.getElementById('manualEntryResults');
    if (!resultsContainer) {
        console.error('Manual entry results container not found');
        return;
    }
    
    resultsContainer.style.display = 'block';
    resultsContainer.innerHTML = generateAnalysisResults(analysis);
}

// ── Human-readable display names ────────────────────────────────────────────
const TEST_LABELS = {
    blood_glucose_fasting: 'Blood Glucose (Fasting)',
    hba1c: 'HbA1c',
    total_cholesterol: 'Total Cholesterol',
    ldl_cholesterol: 'LDL Cholesterol',
    hdl_cholesterol: 'HDL Cholesterol',
    triglycerides: 'Triglycerides',
    hemoglobin: 'Hemoglobin',
    wbc_count: 'WBC Count',
    rbc_count: 'RBC Count',
    platelet_count: 'Platelet Count',
    hematocrit: 'Hematocrit',
    creatinine: 'Creatinine',
    urea: 'Urea / BUN',
    uric_acid: 'Uric Acid',
    sodium: 'Sodium',
    potassium: 'Potassium',
    chloride: 'Chloride',
    alt_sgpt: 'ALT / SGPT',
    ast_sgot: 'AST / SGOT',
    bilirubin: 'Bilirubin',
    alkaline_phosphatase: 'Alkaline Phosphatase',
    thyroid_tsh: 'TSH',
    t3: 'T3',
    t4: 'T4',
    vitamin_d: 'Vitamin D',
    vitamin_b12: 'Vitamin B12',
    serum_iron: 'Serum Iron',
    ferritin: 'Ferritin',
};
function testLabel(name) {
    return TEST_LABELS[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ── Visual range bar ─────────────────────────────────────────────────────────
function rangeBar(value, normalRange, flag) {
    if (!normalRange || normalRange.length < 2) return '';
    const [lo, hi] = normalRange;
    // display window: 50% below lo to 50% above hi
    const span = hi - lo || 1;
    const dispLo = lo - span * 0.5;
    const dispHi = hi + span * 0.5;
    const pct = Math.min(100, Math.max(0, ((value - dispLo) / (dispHi - dispLo)) * 100));
    const normalLoP = Math.max(0, ((lo - dispLo) / (dispHi - dispLo)) * 100);
    const normalHiP = Math.min(100, ((hi - dispLo) / (dispHi - dispLo)) * 100);
    const colour = flag === 'high' ? '#dc3545' : flag === 'low' ? '#fd7e14' : '#198754';
    return `
        <div style="position:relative;height:10px;background:#e9ecef;border-radius:5px;margin-top:4px;">
            <!-- normal zone -->
            <div style="position:absolute;left:${normalLoP}%;width:${normalHiP - normalLoP}%;height:100%;background:#c3e6cb;border-radius:5px;"></div>
            <!-- value marker -->
            <div style="position:absolute;left:calc(${pct}% - 5px);top:-2px;width:10px;height:14px;background:${colour};border-radius:2px;" title="${value}"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:#6c757d;">
            <span>${lo}</span><span style="font-size:0.65rem;">Normal range</span><span>${hi}</span>
        </div>`;
}

function generateAnalysisResults(analysis) {
    if (!analysis) {
        return '<div class="alert alert-warning">No analysis results available</div>';
    }

    const urgentClass = analysis.requires_medical_attention ? 'alert-danger' : 'alert-info';
    let html = `
        <div class="alert ${urgentClass} mt-3">
            ${analysis.requires_medical_attention
                ? '<strong><i class="fas fa-exclamation-triangle me-2"></i>Urgent:</strong> One or more values are critically abnormal. Please see a doctor soon.<br>'
                : ''}
            ${analysis.summary || ''}
        </div>`;

    // ── Interpretations grid ─────────────────────────────────────────────────
    if (analysis.interpretations && analysis.interpretations.length > 0) {
        html += `<h6 class="mt-4 mb-3"><i class="fas fa-list me-2"></i>Test Results (${analysis.interpretations.length})</h6>
        <div class="row g-3">`;
        analysis.interpretations.forEach(interp => {
            const flagColour = interp.flag === 'high' ? 'danger' : interp.flag === 'low' ? 'warning' : 'success';
            const flagIcon   = interp.flag === 'high' ? '↑' : interp.flag === 'low' ? '↓' : '✓';
            const borderCls  = interp.flag ? `border-${flagColour}` : '';
            html += `
            <div class="col-md-6 col-lg-4">
                <div class="card h-100 ${borderCls}" style="border-width:2px;">
                    <div class="card-body p-3">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <strong class="small">${testLabel(interp.test_name)}</strong>
                            <span class="badge bg-${flagColour} ms-1">${flagIcon} ${interp.flag ? interp.flag.toUpperCase() : 'NORMAL'}</span>
                        </div>
                        <div class="fs-4 fw-bold">${interp.value} <small class="text-muted fs-6">${interp.unit || ''}</small></div>
                        <div class="small text-muted mb-1">${interp.interpretation}</div>
                        ${rangeBar(interp.value, interp.normal_range, interp.flag)}
                        ${interp.severity ? `<span class="badge mt-1 severity-badge severity-${interp.severity}">${interp.severity} deviation</span>` : ''}
                    </div>
                </div>
            </div>`;
        });
        html += `</div>`;
    }

    // ── Potential Issues ─────────────────────────────────────────────────────
    if (analysis.potential_issues && analysis.potential_issues.length > 0) {
        html += `<h6 class="mt-4"><i class="fas fa-exclamation-circle me-2 text-warning"></i>Potential Conditions Indicated</h6>
        <div class="row g-2 mb-3">`;
        analysis.potential_issues.forEach(issue => {
            const conf = issue.confidence;
            const bg = conf === 'high' ? 'danger' : conf === 'moderate' ? 'warning' : 'secondary';
            html += `<div class="col-auto">
                <span class="badge bg-${bg} fs-6 p-2">${issue.condition}
                    <span class="ms-1 fw-normal opacity-75">${conf} confidence</span>
                </span></div>`;
        });
        html += `</div>`;
    }

    // ── Recommendations ──────────────────────────────────────────────────────
    if (analysis.recommendations && analysis.recommendations.length > 0) {
        html += `<h6 class="mt-3"><i class="fas fa-lightbulb me-2 text-success"></i>Recommendations</h6>
        <ul class="list-group mb-4">`;
        analysis.recommendations.forEach(rec => {
            const pri = rec.priority;
            const icon = pri === 'high' ? 'fas fa-circle text-danger' : pri === 'moderate' ? 'fas fa-circle text-warning' : 'fas fa-circle text-secondary';
            html += `<li class="list-group-item d-flex gap-3 align-items-start">
                <i class="${icon} mt-1 small"></i>
                <div>
                    <span class="text-capitalize fw-semibold">${rec.category}</span> —
                    ${rec.recommendation}
                </div>
            </li>`;
        });
        html += `</ul>`;
    }

    return html;
}

function loadLabHistory() {
    const userId = window.currentUser?.id || 'demo'; // Fallback to demo user if none set
    
    fetch(`/lab-analysis/history/${userId}`)
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        populateLabHistoryTable(data.lab_history || []);
        populateTestFilters(data.lab_history || []);
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to load lab history: ' + error.message);
    });
}

function populateLabHistoryTable(labHistory) {
    const tbody = document.querySelector('#labHistoryTable tbody');
    if (!tbody) {
        console.error('Lab history table body not found');
        return;
    }
    
    tbody.innerHTML = '';
    
    if (labHistory.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td colspan="6" class="text-center">No lab history found</td>
        `;
        tbody.appendChild(row);
        return;
    }
    
    labHistory.forEach(result => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${new Date(result.test_date).toLocaleDateString()}</td>
            <td>${result.test_name}</td>
            <td>${result.value}</td>
            <td>${result.unit || '-'}</td>
            <td>${result.status}</td>
            <td>
                <button class="btn btn-sm btn-outline-info me-1" title="View Trend">
                    <i class="fas fa-chart-line"></i>
                </button>
                <button class="btn btn-sm btn-outline-primary" title="View Details">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        `;
        
        // Add event listeners to the buttons
        const viewTrendBtn = row.querySelector('.btn-outline-info');
        if (viewTrendBtn) {
            viewTrendBtn.addEventListener('click', () => {
                viewTestDetails(result.result_id);
            });
        }
        
        const viewDetailsBtn = row.querySelector('.btn-outline-primary');
        if (viewDetailsBtn) {
            viewDetailsBtn.addEventListener('click', () => {
                if (result.attached_file_path) {
                    downloadReport(result.attached_file_path);
                } else {
                    viewTestDetails(result.result_id);
                }
            });
        }
        
        tbody.appendChild(row);
    });
}

function populateTestFilters(labHistory) {
    const filterTest = document.getElementById('filterTest');
    const trendTest = document.getElementById('trendTest');
    
    if (!filterTest || !trendTest) {
        console.error('Test filter elements not found');
        return;
    }
    
    // Clear existing options except the first one
    while (filterTest.options.length > 1) {
        filterTest.remove(1);
    }
    
    while (trendTest.options.length > 1) {
        trendTest.remove(1);
    }
    
    // Get unique test names
    const testNames = [...new Set(labHistory.map(result => result.test_name))].filter(Boolean);
    
    // Populate filter dropdown
    testNames.forEach(testName => {
        const option = document.createElement('option');
        option.value = testName;
        option.textContent = testName;
        filterTest.appendChild(option);
        
        const trendOption = option.cloneNode(true);
        trendTest.appendChild(trendOption);
    });
}

function loadAvailableTests() {
    fetch('/lab-analysis/reference-ranges')
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(referenceRanges => {
        window.referenceRanges = referenceRanges;
    })
    .catch(error => {
        console.error('Error loading reference ranges:', error);
    });
}

function filterLabHistory() {
    const startDate = document.getElementById('startDate')?.value;
    const endDate = document.getElementById('endDate')?.value;
    const testFilter = document.getElementById('filterTest')?.value;
    
    const userId = window.currentUser?.id || 'demo';
    let url = `/lab-analysis/history/${userId}?`;
    
    if (startDate) url += `start_date=${startDate}&`;
    if (endDate) url += `end_date=${endDate}&`;
    if (testFilter) url += `test_name=${testFilter}`;
    
    fetch(url)
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        populateLabHistoryTable(data.lab_history || []);
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to filter lab history: ' + error.message);
    });
}

function updateTrendChart() {
    const testName = document.getElementById('trendTest')?.value;
    const period = document.getElementById('trendPeriod')?.value;
    
    if (!testName) {
        const trendStats = document.getElementById('trendStats');
        if (trendStats) {
            trendStats.style.display = 'none';
        }
        
        const canvas = document.getElementById('trendChart');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            if (ctx) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }
        return;
    }
    
    const userId = window.currentUser?.id || 'demo';
    
    fetch(`/lab-analysis/trends/${userId}/${testName}`)
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        displayTrendChart(data, period);
        displayTrendStats(data.trend_analysis);
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to load trend data: ' + error.message);
    });
}

function displayTrendChart(data, period) {
    const ctx = document.getElementById('trendChart')?.getContext('2d');
    if (!ctx) {
        console.error('Trend chart canvas not found');
        return;
    }
    
    // Destroy existing chart if it exists
    if (window.trendChart instanceof Chart) {
        window.trendChart.destroy();
    }
    
    // Filter data based on period
    let chartData = data.chart_data || [];
    if (!chartData.length) {
        return;
    }
    
    const now = new Date();
    
    switch(period) {
        case '1m':
            chartData = chartData.filter(d => new Date(d.date) > new Date(now.getFullYear(), now.getMonth() - 1, now.getDate()));
            break;
        case '3m':
            chartData = chartData.filter(d => new Date(d.date) > new Date(now.getFullYear(), now.getMonth() - 3, now.getDate()));
            break;
        case '6m':
            chartData = chartData.filter(d => new Date(d.date) > new Date(now.getFullYear(), now.getMonth() - 6, now.getDate()));
            break;
        case '1y':
            chartData = chartData.filter(d => new Date(d.date) > new Date(now.getFullYear() - 1, now.getMonth(), now.getDate()));
            break;
    }
    
    if (typeof Chart === 'undefined') {
        console.error('Chart.js is not loaded');
        return;
    }
    
    window.trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.map(d => new Date(d.date).toLocaleDateString()),
            datasets: [{
                label: data.test_name,
                data: chartData.map(d => d.value),
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: `${data.test_name} Trend Analysis`
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    title: {
                        display: true,
                        text: 'Value'
                    }
                }
            }
        }
    });
}

function displayTrendStats(trendAnalysis) {
    const trendStats = document.getElementById('trendStats');
    if (!trendStats) {
        console.error('Trend stats element not found');
        return;
    }
    
    if (!trendAnalysis) {
        trendStats.style.display = 'none';
        return;
    }
    
    trendStats.style.display = 'block';
    
    const avgValue = document.getElementById('avgValue');
    const lastReading = document.getElementById('lastReading');
    const trendDirection = document.getElementById('trendDirection');
    
    if (avgValue) {
        avgValue.textContent = trendAnalysis.mean.toFixed(2);
    }
    
    if (lastReading) {
        lastReading.textContent = trendAnalysis.latest.toFixed(2);
    }
    
    if (trendDirection) {
        trendDirection.textContent = trendAnalysis.trend;
        trendDirection.className = `h4 ${
            trendAnalysis.trend === 'increasing' ? 'text-danger' : 
            trendAnalysis.trend === 'decreasing' ? 'text-success' : 
            'text-info'
        }`;
    }
}

function viewTestDetails(resultId) {
    fetch(`/lab-analysis/result/${resultId}`)
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        // Create modal to display detailed test information
        const modalEl = document.createElement('div');
        modalEl.className = 'modal fade';
        modalEl.id = 'testDetailsModal';
        modalEl.tabIndex = -1;
        modalEl.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Test Details</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p><strong>Test:</strong> ${data.test_name}</p>
                        <p><strong>Value:</strong> ${data.value} ${data.unit || ''}</p>
                        <p><strong>Date:</strong> ${new Date(data.test_date).toLocaleString()}</p>
                        <p><strong>Laboratory:</strong> ${data.lab_name || 'Not specified'}</p>
                        <p><strong>Ordering Physician:</strong> ${data.ordering_physician || 'Not specified'}</p>
                        <p><strong>Notes:</strong> ${data.notes || 'No notes'}</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modalEl);
        
        // Check if Bootstrap is available
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
            
            modalEl.addEventListener('hidden.bs.modal', function () {
                document.body.removeChild(modalEl);
            });
        } else {
            // Fallback if Bootstrap is not available
            alert(`Test Details:\n- Test: ${data.test_name}\n- Value: ${data.value} ${data.unit || ''}\n- Date: ${new Date(data.test_date).toLocaleString()}`);
            document.body.removeChild(modalEl);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to load test details: ' + error.message);
    });
}

function downloadReport(filePath) {
    if (!filePath) {
        showError('File path not specified');
        return;
    }
    
    window.open(`/lab-analysis/download/${encodeURIComponent(filePath)}`, '_blank');
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 end-0 m-3';
    errorDiv.style.zIndex = '9999';
    errorDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(errorDiv);
    
    // Auto dismiss after 5 seconds
    setTimeout(() => {
        if (errorDiv.parentNode) {
            errorDiv.parentNode.removeChild(errorDiv);
        }
    }, 5000);
}

// ── Unit auto-fill when a test is selected ────────────────────────────────────
const TEST_UNITS = {
    blood_glucose_fasting: 'mg/dL', hba1c: '%',
    total_cholesterol: 'mg/dL', ldl_cholesterol: 'mg/dL',
    hdl_cholesterol: 'mg/dL', triglycerides: 'mg/dL',
    hemoglobin: 'g/dL', wbc_count: '×10³/μL', rbc_count: '×10⁶/μL',
    platelet_count: '×10³/μL', hematocrit: '%', creatinine: 'mg/dL',
    urea: 'mg/dL', uric_acid: 'mg/dL', sodium: 'mEq/L',
    potassium: 'mEq/L', chloride: 'mEq/L', alt_sgpt: 'IU/L',
    ast_sgot: 'IU/L', bilirubin: 'mg/dL', alkaline_phosphatase: 'IU/L',
    thyroid_tsh: 'mIU/L', t3: 'ng/dL', t4: 'μg/dL',
    vitamin_d: 'ng/mL', vitamin_b12: 'pg/mL',
    serum_iron: 'μg/dL', ferritin: 'ng/mL',
};

document.addEventListener('change', function(e) {
    if (e.target.classList.contains('test-name')) {
        const row = e.target.closest('.test-entry');
        if (row) {
            const unitInput = row.querySelector('.test-unit');
            if (unitInput && TEST_UNITS[e.target.value]) {
                unitInput.value = TEST_UNITS[e.target.value];
            }
        }
    }
});

// ── Paste text tab ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    const parseBtn = document.getElementById('parsePasteBtn');
    if (parseBtn) {
        parseBtn.addEventListener('click', function() {
            const text = document.getElementById('pasteTextArea')?.value.trim();
            const resultsDiv = document.getElementById('pasteResults');
            if (!text) { showError('Please paste some text first.'); return; }
            parseBtn.disabled = true;
            parseBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Analysing…';
            fetch('/lab-analysis/parse-text', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': getCsrfToken(),
                },
                body: JSON.stringify({text}),
            })
            .then(r => r.json())
            .then(data => {
                parseBtn.disabled = false;
                parseBtn.innerHTML = '<i class="fas fa-search me-2"></i>Analyse';
                if (resultsDiv) {
                    resultsDiv.style.display = 'block';
                    resultsDiv.innerHTML = data.status === 'success'
                        ? `<div class="alert alert-success mb-3"><i class="fas fa-check-circle me-2"></i>Detected <strong>${data.detected_tests}</strong> test(s).</div>`
                          + generateAnalysisResults(data.analysis)
                        : `<div class="alert alert-warning">${data.message || data.error || 'Could not parse text.'}</div>`;
                }
            })
            .catch(err => {
                parseBtn.disabled = false;
                parseBtn.innerHTML = '<i class="fas fa-search me-2"></i>Analyse';
                showError('Failed to parse text: ' + err.message);
            });
        });
    }

    // Set up filter event listeners
    const startDateEl = document.getElementById('startDate');
    const endDateEl = document.getElementById('endDate');
    const filterTestEl = document.getElementById('filterTest');
    const trendTestEl = document.getElementById('trendTest');
    const trendPeriodEl = document.getElementById('trendPeriod');

    if (startDateEl) startDateEl.addEventListener('change', filterLabHistory);
    if (endDateEl) endDateEl.addEventListener('change', filterLabHistory);
    if (filterTestEl) filterTestEl.addEventListener('change', filterLabHistory);
    if (trendTestEl) trendTestEl.addEventListener('change', updateTrendChart);
    if (trendPeriodEl) trendPeriodEl.addEventListener('change', updateTrendChart);
});