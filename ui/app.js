document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const statusMsg = document.getElementById('upload-status');
    const resultsSection = document.getElementById('results-section');
    const reportsContainer = document.getElementById('reports-container');

    // Manejo visual de Drag & Drop
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    dropZone.addEventListener('drop', (e) => {
        let dt = e.dataTransfer;
        let files = dt.files;
        handleFiles(files);
    });

    fileInput.addEventListener('change', function() {
        handleFiles(this.files);
    });

    function handleFiles(files) {
        if (!files || files.length === 0) return;
        
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }

        uploadAndProcess(formData);
    }

    async function uploadAndProcess(formData) {
        statusMsg.textContent = 'Analizando documentos con Cotejo AI... esto puede tardar unos segundos.';
        statusMsg.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        reportsContainer.innerHTML = '';

        try {
            const response = await fetch('/audit', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error('Error en el servidor');
            
            const data = await response.json();
            renderReports(data.reports);
            
            statusMsg.classList.add('hidden');
            resultsSection.classList.remove('hidden');
        } catch (error) {
            statusMsg.textContent = 'Ocurrió un error al procesar las facturas.';
            statusMsg.style.color = '#ef4444';
            console.error(error);
        }
    }

    function renderReports(reports) {
        reports.forEach(report => {
            const card = document.createElement('div');
            card.className = 'report-card';
            
            const isValid = report.es_valida;
            const badgeClass = isValid ? 'valid' : 'invalid';
            const badgeText = isValid ? 'Sin anomalías críticas' : 'Requiere revisión manual';

            let hallazgosHtml = '';
            if (report.hallazgos.length === 0) {
                hallazgosHtml = '<p style="color: #94a3b8; font-style: italic;">No se detectaron inconsistencias.</p>';
            } else {
                report.hallazgos.forEach(h => {
                    const citasHtml = h.citas.map(c => `<span class="citation">Pág. ${c.page}</span>`).join(' ');
                    hallazgosHtml += `
                        <div class="finding ${h.gravedad}">
                            <div class="finding-title">
                                <span>[${h.tipo.toUpperCase()}]</span>
                                <div>${citasHtml}</div>
                            </div>
                            <p>${h.mensaje}</p>
                        </div>
                    `;
                });
            }

            card.innerHTML = `
                <div class="report-header">
                    <h3>📄 ${report.archivo_origen}</h3>
                    <span class="badge ${badgeClass}">${badgeText}</span>
                </div>
                <div class="findings-list">
                    ${hallazgosHtml}
                </div>
            `;
            reportsContainer.appendChild(card);
        });
    }
});
