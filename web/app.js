// SABADARMON MSKT PACS APP.JS
let activeTabId = 'studies-archive';

// -------------------------------------------------------------
// 1. LIGHTWEIGHT MODAL / DIALOG (YENGIL MARKAZIY OYNA)
// -------------------------------------------------------------
function showDialog({ title = "Bildirishnoma", message, onConfirm = null, confirmText = "Ha", cancelText = "Bekor qilish" }) {
    const backdrop = document.getElementById('custom-modal-backdrop');
    const titleEl = document.getElementById('modal-title');
    const msgEl = document.getElementById('modal-message');
    const footerEl = document.getElementById('modal-footer');
    
    if (!backdrop || !titleEl || !msgEl || !footerEl) return;

    titleEl.innerText = title;
    msgEl.innerText = message;
    
    if (onConfirm) {
        footerEl.innerHTML = `
            <button class="btn btn-secondary btn-sm" onclick="closeCustomModal()">${cancelText}</button>
            <button class="btn btn-primary btn-sm" id="btn-modal-confirm">${confirmText}</button>
        `;
        document.getElementById('btn-modal-confirm').onclick = () => {
            closeCustomModal();
            onConfirm();
        };
    } else {
        footerEl.innerHTML = `<button class="btn btn-primary btn-sm" onclick="closeCustomModal()">Tushunarli</button>`;
    }
    backdrop.classList.add('active');
}

function closeCustomModal() {
    const backdrop = document.getElementById('custom-modal-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

function handleBackdropClick(e) {
    if (e.target.id === 'custom-modal-backdrop') {
        closeCustomModal();
    }
}

// -------------------------------------------------------------
// 2. TAB BOSHQARUVI
// -------------------------------------------------------------
function switchTab(tabId) {
    activeTabId = tabId;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));

    const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick')?.includes(tabId));
    if (activeBtn) activeBtn.classList.add('active');

    const targetTab = document.getElementById(`tab-${tabId}`);
    if (targetTab) targetTab.classList.add('active');

    if (tabId === 'studies-archive') loadStudies();
    if (tabId === 'system-logs') loadLogs();
}

function closeAlert() {
    const banner = document.getElementById('ct-direct-alert');
    if (banner) banner.style.display = 'none';
}

// -------------------------------------------------------------
// 3. ARXIV VA BEMORLAR BOSHQARUVI (727+ STUDIES)
// -------------------------------------------------------------
let allStudies = [];
let filteredStudies = [];
let currentStudyFilter = 'ALL';
let currentSearchQuery = '';
let currentStudyPage = 1;
let studyPageSize = 50;
let selectedStudyIds = new Set();
let activeProgressPollTimer = null;

function formatUzbekDate(dateStr) {
    if (!dateStr) return "";
    const months = {
        1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel",
        5: "may", 6: "iyun", 7: "iyul", 8: "avgust",
        9: "sentabr", 10: "oktabr", 11: "noyabr", 12: "dekabr"
    };
    const s = String(dateStr).trim();
    const digits = s.replace(/\D/g, "");
    if (digits.length >= 8) {
        const y = parseInt(digits.slice(0, 4));
        const m = parseInt(digits.slice(4, 6));
        const d = parseInt(digits.slice(6, 8));
        if (m >= 1 && m <= 12 && d >= 1 && d <= 31) {
            const dd = d < 10 ? '0' + d : d;
            return `${dd}-${months[m]} ${y}`;
        }
    }
    return s;
}

function updateSelectedCount() {
    const countSpan = document.getElementById('selected-count');
    const batchBtn = document.getElementById('btn-batch-telegram');
    const archiveCountSpan = document.getElementById('archive-selected-count');
    const archiveBtn = document.getElementById('btn-batch-archive');
    const deleteCountSpan = document.getElementById('delete-selected-count');
    const deleteBtn = document.getElementById('btn-batch-delete-local');

    // Menyu elementlari
    const menuArchiveSpan = document.getElementById('menu-archive-selected-count');
    const menuArchiveBtn = document.getElementById('menu-item-batch-archive');
    const menuTgSpan = document.getElementById('menu-selected-count');
    const menuTgBtn = document.getElementById('menu-item-batch-telegram');
    const menuDelSpan = document.getElementById('menu-delete-selected-count');
    const menuDelBtn = document.getElementById('menu-item-batch-delete');

    const cnt = selectedStudyIds.size;
    if (countSpan) countSpan.innerText = cnt;
    if (batchBtn) batchBtn.disabled = (cnt === 0);
    if (archiveCountSpan) archiveCountSpan.innerText = cnt;
    if (archiveBtn) archiveBtn.disabled = (cnt === 0);
    if (deleteCountSpan) deleteCountSpan.innerText = cnt;
    if (deleteBtn) deleteBtn.disabled = (cnt === 0);

    if (menuArchiveSpan) menuArchiveSpan.innerText = cnt;
    if (menuArchiveBtn) menuArchiveBtn.disabled = (cnt === 0);
    if (menuTgSpan) menuTgSpan.innerText = cnt;
    if (menuTgBtn) menuTgBtn.disabled = (cnt === 0);
    if (menuDelSpan) menuDelSpan.innerText = cnt;
    if (menuDelBtn) menuDelBtn.disabled = (cnt === 0);
}

function toggleStudySelect(id, checkbox) {
    if (checkbox.checked) {
        selectedStudyIds.add(id);
    } else {
        selectedStudyIds.delete(id);
    }
    updateSelectedCount();
    
    const allCheckboxes = document.querySelectorAll('.study-checkbox');
    const master = document.getElementById('select-all-studies');
    if (master && allCheckboxes.length > 0) {
        master.checked = Array.from(allCheckboxes).every(cb => cb.checked);
    }
}

function toggleSelectAllStudies(masterCheckbox) {
    const allCheckboxes = document.querySelectorAll('.study-checkbox');
    allCheckboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
        const id = parseInt(cb.value);
        if (masterCheckbox.checked) {
            selectedStudyIds.add(id);
        } else {
            selectedStudyIds.delete(id);
        }
    });
    updateSelectedCount();
}

let currentDatePreset = localStorage.getItem('pacs_date_preset') || 'TODAY';
let currentExamFilter = 'ALL';
let currentSortBy = localStorage.getItem('pacs_sort_by') || 'DATE_DESC';
let currentSortColumn = 'DATE';
let currentSortDirection = 'DESC'; // 'ASC' yoki 'DESC'

// Boshlang'ich saralash sozlamasini o'qish
if (currentSortBy.includes('_')) {
    const lastUnderscore = currentSortBy.lastIndexOf('_');
    const dir = currentSortBy.substring(lastUnderscore + 1);
    const col = currentSortBy.substring(0, lastUnderscore);
    if (dir === 'ASC' || dir === 'DESC') {
        currentSortColumn = col;
        currentSortDirection = dir;
    }
}

// Foydalanuvchi tanlagan sanasi, saralashi va sahifa hajmini tiklash (Preferences Restore)
function initPreferences() {
    // 1. Sana filtri sozlamasini tiklash
    const savedDatePreset = localStorage.getItem('pacs_date_preset') || 'TODAY';
    currentDatePreset = savedDatePreset;
    const datePresetEl = document.getElementById('filter-date-preset');
    if (datePresetEl) {
        datePresetEl.value = currentDatePreset;
    }
    const customDateInput = document.getElementById('filter-date-custom');
    if (customDateInput) {
        if (currentDatePreset === 'CUSTOM') {
            customDateInput.style.display = 'inline-block';
            customDateInput.value = localStorage.getItem('pacs_date_custom') || '';
        } else {
            customDateInput.style.display = 'none';
        }
    }

    // 2. Sahifa hajmi (Page Size) sozlamasini tiklash
    const savedPageSize = localStorage.getItem('pacs_page_size');
    if (savedPageSize) {
        studyPageSize = parseInt(savedPageSize, 10) || 50;
        const selTop = document.getElementById('select-page-size-top');
        if (selTop) selTop.value = String(studyPageSize);
        const selBtm = document.getElementById('select-page-size-bottom');
        if (selBtm) selBtm.value = String(studyPageSize);
    }

    // 3. Saralash sozlamasini tiklash
    const savedSort = localStorage.getItem('pacs_sort_by');
    if (savedSort) {
        currentSortBy = savedSort;
        if (savedSort.includes('_')) {
            const lastUnderscore = savedSort.lastIndexOf('_');
            const dir = savedSort.substring(lastUnderscore + 1);
            const col = savedSort.substring(0, lastUnderscore);
            if (dir === 'ASC' || dir === 'DESC') {
                currentSortColumn = col;
                currentSortDirection = dir;
            }
        }
        const sortSelect = document.getElementById('filter-sort-by');
        if (sortSelect) sortSelect.value = savedSort;
    }
}

// Har bir bemorning jarayon va navbat ustuvorlik ballini hisoblash
function getStudyQueueScore(s) {
    const stage = s.active_stage || s.progress_stage || '';
    const text = s.active_text || s.progress_text || '';

    // 1. Faol ishlayotgan jarayonlar (eng yuqori ustuvorlik)
    if (stage === 'UPLOADING_TG') return 10;   // Telegramga yuklanmoqda
    if (stage === 'ARCHIVING') return 20;      // ZIP qilinmoqda
    if (stage === 'DOWNLOADING_CT') return 30; // KT apparatidan yuklanmoqda
    if (stage === 'DOWNLOADING_TG') return 40; // Telegramdan yuklab olinmoqda
    if (s.telegram_status === 'SENDING' || s.telegram_status === 'RETRIEVING') return 45;

    // 2. Navbatda kutayotganlar: #1, #2, #3 tartib raqami bo'yicha
    let pos = 999;
    const match = text.match(/#(\d+)/);
    if (match) {
        pos = parseInt(match[1], 10) || 999;
    }

    // Telegram navbatidagilar (#1 -> 101, #2 -> 102...)
    if (stage === 'QUEUED_TG') return 100 + pos;
    // ZIP navbatidagilar (#1 -> 301, #2 -> 302...)
    if (stage === 'QUEUED_ARCHIVE') return 300 + pos;
    // KT navbatidagilar (#1 -> 501, #2 -> 502...)
    if (stage === 'QUEUED_CT') return 500 + pos;

    // 3. Navbatda bo'lmagan boshqa holatlar
    if (s.telegram_status === 'FAILED') return 1000;
    if (s.telegram_status === 'PENDING') return 2000;
    if (s.telegram_status === 'ON_CT_DEVICE') return 3000;
    if (s.telegram_status === 'SENT') return 4000;

    return 5000;
}

// Jadval sarlavhasi (TH) belgilari va faolligini yangilash
function updateTableHeaderSortIcons() {
    const columns = ['DATE', 'PATIENT_ID', 'PATIENT_NAME', 'STUDY_DESC', 'INSTANCES', 'LOCAL_STORAGE', 'QUEUE_ORDER'];
    columns.forEach(col => {
        const th = document.getElementById(`th-col-${col}`);
        const icon = document.getElementById(`sort-icon-${col}`);
        if (th) {
            if (col === currentSortColumn) {
                th.classList.add('active-sort');
                if (icon) {
                    icon.innerText = (currentSortDirection === 'ASC') ? '▲' : '▼';
                    icon.style.color = '#0284c7';
                }
            } else {
                th.classList.remove('active-sort');
                if (icon) {
                    icon.innerText = '⇅';
                    icon.style.color = '#94a3b8';
                }
            }
        }
    });
}

// Ustun sarlavhasini bosganda saralash (Column click sorting)
function handleColumnSort(colKey) {
    if (currentSortColumn === colKey) {
        // Bir xil ustun qayta bosilsa yo'nalishni almashtirish
        currentSortDirection = (currentSortDirection === 'ASC') ? 'DESC' : 'ASC';
    } else {
        currentSortColumn = colKey;
        // Boshlang'ich optimal yo'nalish
        if (colKey === 'DATE' || colKey === 'INSTANCES' || colKey === 'LOCAL_STORAGE') {
            currentSortDirection = 'DESC';
        } else if (colKey === 'QUEUE_ORDER') {
            currentSortDirection = 'ASC'; // Navbatda #1 eng oldinda chiqishi uchun
        } else {
            currentSortDirection = 'ASC'; // Nom, ID, Tekshiruv A-Z
        }
    }

    currentSortBy = `${currentSortColumn}_${currentSortDirection}`;
    localStorage.setItem('pacs_sort_by', currentSortBy);

    // Select dropdownni yangilash
    const sortSelect = document.getElementById('filter-sort-by');
    if (sortSelect) {
        if (sortSelect.querySelector(`option[value="${currentSortBy}"]`)) {
            sortSelect.value = currentSortBy;
        } else if (sortSelect.querySelector(`option[value="${currentSortColumn}_ASC"]`)) {
            sortSelect.value = `${currentSortColumn}_ASC`;
        }
    }

    currentStudyPage = 1;
    applyStudyFilters();
}

function populateExamFilterOptions() {
    const examSelect = document.getElementById('filter-exam-select');
    if (!examSelect) return;
    const currentVal = examSelect.value;
    const exams = new Set();
    allStudies.forEach(s => {
        const desc = (s.study_description || '').trim();
        if (desc && desc !== '-' && desc !== 'None') {
            exams.add(desc);
        }
    });
    const sortedExams = Array.from(exams).sort();
    examSelect.innerHTML = `<option value="ALL">Barcha sohalar</option>` + sortedExams.map(e => `<option value="${e}">${e}</option>`).join('');
    if (sortedExams.includes(currentVal)) {
        examSelect.value = currentVal;
    }
}

function handleDatePresetChange(val) {
    currentDatePreset = val;
    localStorage.setItem('pacs_date_preset', val);
    const customInput = document.getElementById('filter-date-custom');
    if (customInput) {
        customInput.style.display = (val === 'CUSTOM') ? 'inline-block' : 'none';
        if (val !== 'CUSTOM') {
            customInput.value = '';
            localStorage.removeItem('pacs_date_custom');
        }
    }
    currentStudyPage = 1;
    applyStudyFilters();
}

function handleCustomDateChange(val) {
    if (val) {
        localStorage.setItem('pacs_date_custom', val);
    } else {
        localStorage.removeItem('pacs_date_custom');
    }
    currentStudyPage = 1;
    applyStudyFilters();
}

function handleSortChange(val) {
    currentSortBy = val;
    localStorage.setItem('pacs_sort_by', currentSortBy);
    if (val.includes('_')) {
        const lastUnderscore = val.lastIndexOf('_');
        const dir = val.substring(lastUnderscore + 1);
        const col = val.substring(0, lastUnderscore);
        if (dir === 'ASC' || dir === 'DESC') {
            currentSortColumn = col;
            currentSortDirection = dir;
        } else {
            currentSortColumn = val;
            currentSortDirection = 'ASC';
        }
    } else {
        currentSortColumn = val;
        currentSortDirection = 'ASC';
    }
    currentStudyPage = 1;
    applyStudyFilters();
}

function resetAllFilters() {
    currentSearchQuery = '';
    currentStudyFilter = 'ALL';
    currentDatePreset = 'ALL';
    localStorage.setItem('pacs_date_preset', 'ALL');
    localStorage.removeItem('pacs_date_custom');
    currentExamFilter = 'ALL';
    currentSortBy = 'DATE_DESC';
    currentSortColumn = 'DATE';
    currentSortDirection = 'DESC';
    localStorage.setItem('pacs_sort_by', 'DATE_DESC');

    const searchInput = document.getElementById('study-search-input');
    if (searchInput) searchInput.value = '';
    const datePreset = document.getElementById('filter-date-preset');
    if (datePreset) datePreset.value = 'ALL';
    const dateCustom = document.getElementById('filter-date-custom');
    if (dateCustom) { dateCustom.value = ''; dateCustom.style.display = 'none'; }
    const examSelect = document.getElementById('filter-exam-select');
    if (examSelect) examSelect.value = 'ALL';
    const sortSelect = document.getElementById('filter-sort-by');
    if (sortSelect) sortSelect.value = 'DATE_DESC';

    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    const allBtn = document.querySelector('.filter-pill[onclick*="ALL"]');
    if (allBtn) allBtn.classList.add('active');

    currentStudyPage = 1;
    applyStudyFilters();
}

function isStudyInProgress(s) {
    const st = s.active_stage || s.progress_stage || '';
    if (['DOWNLOADING_CT', 'QUEUED_CT', 'ARCHIVING', 'QUEUED_ARCHIVE', 'UPLOADING_TG', 'QUEUED_TG', 'DOWNLOADING_TG'].includes(st)) {
        return true;
    }
    if (s.telegram_status === 'RETRIEVING' || s.telegram_status === 'SENDING') {
        return true;
    }
    return false;
}

function updateFilterCounts() {
    const total = allStudies.length;
    const inProgressCount = allStudies.filter(s => isStudyInProgress(s)).length;
    const storedCount = allStudies.filter(s => s.has_local_copy).length;
    const ctCount = allStudies.filter(s => s.telegram_status === 'ON_CT_DEVICE').length;
    const sentCount = allStudies.filter(s => s.telegram_status === 'SENT').length;
    const failedCount = allStudies.filter(s => s.telegram_status === 'FAILED').length;

    const elAll = document.getElementById('filter-all-count');
    const elProg = document.getElementById('filter-progress-count');
    const elStored = document.getElementById('filter-stored-count');
    const elCt = document.getElementById('filter-ct-count');
    const elSent = document.getElementById('filter-sent-count');
    const elFailed = document.getElementById('filter-failed-count');

    if (elAll) elAll.innerText = total;
    if (elProg) elProg.innerText = inProgressCount;
    if (elStored) elStored.innerText = storedCount;
    if (elCt) elCt.innerText = ctCount;
    if (elSent) elSent.innerText = sentCount;
    if (elFailed) elFailed.innerText = failedCount;
}

function handleStudySearch(query) {
    currentSearchQuery = (query || '').toLowerCase().trim();
    currentStudyPage = 1;
    applyStudyFilters();
}

function setStudyFilter(filterKey, buttonElem) {
    currentStudyFilter = filterKey;
    currentStudyPage = 1;
    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    if (buttonElem) buttonElem.classList.add('active');

    // Agar "Jarayonda" tanlansa, avtomatik tarzda jarayon va navbat tartibiga o'tkazish
    if (filterKey === 'IN_PROGRESS') {
        currentSortColumn = 'QUEUE_ORDER';
        currentSortDirection = 'ASC';
        currentSortBy = 'QUEUE_ORDER_ASC';
        const sortSelect = document.getElementById('filter-sort-by');
        if (sortSelect) sortSelect.value = 'QUEUE_ORDER_ASC';
    }

    applyStudyFilters();
}

function applyStudyFilters() {
    const examSelect = document.getElementById('filter-exam-select');
    const selectedExam = examSelect ? examSelect.value : 'ALL';
    const customDateInput = document.getElementById('filter-date-custom');
    const customDateVal = customDateInput && customDateInput.value ? customDateInput.value.replace(/-/g, '') : (localStorage.getItem('pacs_date_custom') || '').replace(/-/g, '');

    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    const todayStr = `${y}${m}${d}`;
    const thisMonthPrefix = `${y}${m}`;

    const yest = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    const yesterdayStr = `${yest.getFullYear()}${String(yest.getMonth() + 1).padStart(2, '0')}${String(yest.getDate()).padStart(2, '0')}`;

    const sevenDaysAgo = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7);
    const sevenDaysAgoStr = `${sevenDaysAgo.getFullYear()}${String(sevenDaysAgo.getMonth() + 1).padStart(2, '0')}${String(sevenDaysAgo.getDate()).padStart(2, '0')}`;

    filteredStudies = allStudies.filter(s => {
        // Status pill filter
        if (currentStudyFilter === 'IN_PROGRESS') {
            if (!isStudyInProgress(s)) return false;
        } else if (currentStudyFilter === 'LOCAL_STORED') {
            if (!s.has_local_copy) return false;
        } else if (currentStudyFilter === 'ON_CT_DEVICE') {
            if (s.telegram_status !== 'ON_CT_DEVICE') return false;
        } else if (currentStudyFilter === 'SENT') {
            if (s.telegram_status !== 'SENT') return false;
        } else if (currentStudyFilter === 'FAILED') {
            if (s.telegram_status !== 'FAILED') return false;
        }

        // Exam description filter
        if (selectedExam !== 'ALL') {
            if ((s.study_description || '').trim() !== selectedExam) return false;
        }

        // Date filter
        const sDate = String(s.study_date || '').replace(/\D/g, '');
        if (currentDatePreset === 'TODAY') {
            if (sDate !== todayStr) return false;
        } else if (currentDatePreset === 'YESTERDAY') {
            if (sDate !== yesterdayStr) return false;
        } else if (currentDatePreset === 'LAST_7_DAYS') {
            if (sDate < sevenDaysAgoStr || sDate > todayStr) return false;
        } else if (currentDatePreset === 'THIS_MONTH') {
            if (!sDate.startsWith(thisMonthPrefix)) return false;
        } else if (currentDatePreset === 'CUSTOM' && customDateVal) {
            if (sDate !== customDateVal) return false;
        }

        // Search query filter (F.I.Sh, ID, description, date)
        if (currentSearchQuery) {
            const name = (s.patient_name || '').toLowerCase();
            const pid = (s.patient_id || '').toLowerCase();
            const desc = (s.study_description || '').toLowerCase();
            const date = (s.study_date || '').toLowerCase();
            if (!name.includes(currentSearchQuery) && !pid.includes(currentSearchQuery) && !desc.includes(currentSearchQuery) && !date.includes(currentSearchQuery)) {
                return false;
            }
        }
        return true;
    });

    // Jadval ustunlari piktogrammalarini yangilash
    updateTableHeaderSortIcons();

    // Saralash (Sorting)
    filteredStudies.sort((a, b) => {
        const dir = (currentSortDirection === 'DESC') ? -1 : 1;

        if (currentSortColumn === 'QUEUE_ORDER') {
            const scoreA = getStudyQueueScore(a);
            const scoreB = getStudyQueueScore(b);
            if (scoreA !== scoreB) {
                return (scoreA - scoreB) * dir;
            }
            // Agar jarayon/navbat bir xil bo'lsa, yangi sanalilar oldinda
            return String(b.study_date || '').localeCompare(String(a.study_date || '')) ||
                   String(b.study_time || '').localeCompare(String(a.study_time || ''));
        }

        if (currentSortColumn === 'DATE') {
            const comp = String(a.study_date || '').localeCompare(String(b.study_date || '')) ||
                         String(a.study_time || '').localeCompare(String(b.study_time || ''));
            return comp * dir;
        }

        if (currentSortColumn === 'PATIENT_ID') {
            const idA = String(a.patient_id || '').toLowerCase();
            const idB = String(b.patient_id || '').toLowerCase();
            return idA.localeCompare(idB) * dir;
        }

        if (currentSortColumn === 'PATIENT_NAME') {
            const nameA = String(a.patient_name || '').toLowerCase();
            const nameB = String(b.patient_name || '').toLowerCase();
            return nameA.localeCompare(nameB) * dir;
        }

        if (currentSortColumn === 'STUDY_DESC') {
            const descA = String(a.study_description || '').toLowerCase();
            const descB = String(b.study_description || '').toLowerCase();
            return descA.localeCompare(descB) * dir;
        }

        if (currentSortColumn === 'INSTANCES') {
            const cntA = Number(a.instances_count) || 0;
            const cntB = Number(b.instances_count) || 0;
            return (cntA - cntB) * dir;
        }

        if (currentSortColumn === 'LOCAL_STORAGE') {
            const hasA = a.has_local_copy ? 1 : 0;
            const hasB = b.has_local_copy ? 1 : 0;
            if (hasA !== hasB) {
                return (hasA - hasB) * dir;
            }
            const sizeA = Number(a.archive_size_bytes) || 0;
            const sizeB = Number(b.archive_size_bytes) || 0;
            return (sizeA - sizeB) * dir;
        }

        // Qadimgi fallback saralashlar
        if (currentSortBy === 'DATE_DESC') {
            return String(b.study_date || '').localeCompare(String(a.study_date || '')) || String(b.study_time || '').localeCompare(String(a.study_time || ''));
        } else if (currentSortBy === 'DATE_ASC') {
            return String(a.study_date || '').localeCompare(String(b.study_date || '')) || String(a.study_time || '').localeCompare(String(b.study_time || ''));
        } else if (currentSortBy === 'NAME_ASC') {
            return String(a.patient_name || '').localeCompare(String(b.patient_name || ''));
        } else if (currentSortBy === 'NAME_DESC') {
            return String(b.patient_name || '').localeCompare(String(a.patient_name || ''));
        } else if (currentSortBy === 'INSTANCES_DESC') {
            return (b.instances_count || 0) - (a.instances_count || 0);
        } else if (currentSortBy === 'INSTANCES_ASC') {
            return (a.instances_count || 0) - (b.instances_count || 0);
        }
        return 0;
    });

    renderStudiesTable();
}

function changePageSize(newSize) {
    studyPageSize = parseInt(newSize) || 50;
    localStorage.setItem('pacs_page_size', String(studyPageSize));
    currentStudyPage = 1;
    
    // Ikkala selektorni sinxronlash
    const topSel = document.getElementById('select-page-size-top');
    if (topSel) topSel.value = String(studyPageSize);
    const btmSel = document.getElementById('select-page-size-bottom');
    if (btmSel) btmSel.value = String(studyPageSize);

    renderStudiesTable();
}

function goToStudyPage(pageNum) {
    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    if (pageNum >= 1 && pageNum <= totalPages) {
        currentStudyPage = pageNum;
        renderStudiesTable();

        // Agar pastdan bosilgan bo'lsa, jadval boshiga silliq olib chiqish
        const tableCard = document.querySelector('.table-responsive');
        if (tableCard) {
            tableCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
}

function changeStudyPage(delta) {
    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    const newPage = currentStudyPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        goToStudyPage(newPage);
    }
}

function renderGooglePagination() {
    const container = document.getElementById('bottom-google-pagination');
    if (!container) return;

    if (filteredStudies.length === 0) {
        container.innerHTML = '';
        return;
    }

    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    const startIdx = (currentStudyPage - 1) * studyPageSize;
    const endIdx = Math.min(startIdx + studyPageSize, filteredStudies.length);

    // Google ranglar palitrasi: Moviy, Qizil, Sariq, Yashil
    const colors = ['#4285F4', '#EA4335', '#FBBC05', '#34A853'];

    // Ko'rsatiladigan sahifalar oralig'i (maksimal 10 ta sahifa darchasi)
    const maxVisible = 10;
    let startPage = Math.max(1, currentStudyPage - Math.floor(maxVisible / 2));
    let endPage = startPage + maxVisible - 1;
    if (endPage > totalPages) {
        endPage = totalPages;
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    // Har bir sahifa uchun Google harflari ('o' lar)
    let lettersHtml = '';
    for (let p = startPage; p <= endPage; p++) {
        const isActive = (p === currentStudyPage);
        const color = isActive ? '#EA4335' : colors[(p - 1) % colors.length];
        lettersHtml += `
            <div class="google-letter-col ${isActive ? 'active' : ''}" onclick="goToStudyPage(${p})" title="${p}-sahifaga o'tish">
                <span class="g-char" style="color: ${color}; ${isActive ? 'font-size: 2.3rem;' : ''}">o</span>
                <span class="g-num">${p}</span>
            </div>
        `;
    }

    const hasPrev = currentStudyPage > 1;
    const hasNext = currentStudyPage < totalPages;

    const prevHtml = hasPrev
        ? `<div class="google-nav-btn" onclick="goToStudyPage(${currentStudyPage - 1})" title="Oldingi sahifa">
               <span style="font-size: 1.15rem; line-height: 1;">‹</span> Oldingisi
           </div>`
        : `<div class="google-nav-btn disabled">‹ Oldingisi</div>`;

    const nextHtml = hasNext
        ? `<div class="google-nav-btn" onclick="goToStudyPage(${currentStudyPage + 1})" title="Keyingi sahifa">
               Keyingisi <span style="font-size: 1.15rem; line-height: 1;">›</span>
           </div>`
        : `<div class="google-nav-btn disabled">Keyingisi ›</div>`;

    container.innerHTML = `
        <div class="google-brand-title">
            <span class="brand-leaf">🌿</span>
            <span class="brand-word">Sabadarmon</span>
            <span class="brand-sub">MSKT PACS & Worklist</span>
        </div>
        <div class="google-letters-row">
            ${prevHtml}
            <div style="display: flex; align-items: flex-end; gap: 2px;">
                <span class="g-char" style="color: #4285F4; margin-right: 1px;">S</span>
                ${lettersHtml}
                <span class="g-char" style="color: #4285F4; margin-left: 1px;">n</span>
            </div>
            ${nextHtml}
        </div>
        <div class="google-bottom-meta">
            <div>
                Ko'rsatilmoqda: <strong>${startIdx + 1}–${endIdx}</strong> / Jami: <strong>${filteredStudies.length}</strong> ta bemor (${currentStudyPage} / ${totalPages} sahifa)
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-weight: 600;">📄 Sahifada:</span>
                <select id="select-page-size-bottom" class="form-input" style="width: auto; padding: 4px 8px; margin: 0; font-weight: 600;" onchange="changePageSize(this.value)">
                    <option value="50" ${studyPageSize === 50 ? 'selected' : ''}>50 ta bemor</option>
                    <option value="100" ${studyPageSize === 100 ? 'selected' : ''}>100 ta bemor</option>
                    <option value="200" ${studyPageSize === 200 ? 'selected' : ''}>200 ta bemor</option>
                    <option value="500" ${studyPageSize === 500 ? 'selected' : ''}>500 ta bemor</option>
                    <option value="1000" ${studyPageSize === 1000 ? 'selected' : ''}>1000 ta bemor</option>
                    <option value="999999" ${studyPageSize >= 999999 ? 'selected' : ''}>Barchasi (Hammasi)</option>
                </select>
            </div>
        </div>
    `;
}

function renderStudiesTable() {
    const tbody = document.getElementById('studies-tbody');
    const master = document.getElementById('select-all-studies');
    if (master) master.checked = false;

    if (filteredStudies.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: #94a3b8; padding: 24px;">Hech qanday tekshiruv topilmadi.</td></tr>`;
        
        const topInfo = document.getElementById('top-pagination-info');
        const topTotal = document.getElementById('top-pagination-total');
        const topPageDisp = document.getElementById('top-page-num-display');
        const btnTopPrev = document.getElementById('btn-top-prev');
        const btnTopNext = document.getElementById('btn-top-next');
        if (topInfo) topInfo.innerText = "0 - 0";
        if (topTotal) topTotal.innerText = "0";
        if (topPageDisp) topPageDisp.innerText = "1 / 1";
        if (btnTopPrev) btnTopPrev.disabled = true;
        if (btnTopNext) btnTopNext.disabled = true;

        renderGooglePagination();
        return;
    }

    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    if (currentStudyPage > totalPages) currentStudyPage = totalPages;

    const startIdx = (currentStudyPage - 1) * studyPageSize;
    const endIdx = Math.min(startIdx + studyPageSize, filteredStudies.length);
    const pageItems = filteredStudies.slice(startIdx, endIdx);

    // Yuqori sahifalash satrini yangilash
    const topInfo = document.getElementById('top-pagination-info');
    const topTotal = document.getElementById('top-pagination-total');
    const topPageDisp = document.getElementById('top-page-num-display');
    const btnTopPrev = document.getElementById('btn-top-prev');
    const btnTopNext = document.getElementById('btn-top-next');
    const selTopSize = document.getElementById('select-page-size-top');

    if (topInfo) topInfo.innerText = `${startIdx + 1}–${endIdx}`;
    if (topTotal) topTotal.innerText = filteredStudies.length;
    if (topPageDisp) topPageDisp.innerText = `${currentStudyPage} / ${totalPages}`;
    if (btnTopPrev) btnTopPrev.disabled = (currentStudyPage <= 1);
    if (btnTopNext) btnTopNext.disabled = (currentStudyPage >= totalPages);
    if (selTopSize) selTopSize.value = String(studyPageSize);

    // Pastki Google sahifalashni chizish
    renderGooglePagination();

    tbody.innerHTML = pageItems.map(s => {
        const sizeMb = s.archive_size_bytes ? (s.archive_size_bytes / (1024 * 1024)).toFixed(1) + ' MB' : '-';
        const uzDate = formatUzbekDate(s.study_date);
        const isChecked = selectedStudyIds.has(s.id);

        // 1. Mahalliy xotirada saqlanish holati (30 kunlik muddat)
        let storageBadge = '';
        if (s.has_local_copy) {
            storageBadge = `
                <span class="badge-storage-local" title="Fayllar diskda mavjud">💾 Serverda (${sizeMb})</span>
                <div style="color: #64748b; font-size: 0.73rem; margin-top: 3px;">🕒 ${s.days_remaining} kun qoldi</div>
            `;
        } else {
            storageBadge = `<span class="badge-storage-remote" title="Fayllar faqat KT apparatida saqlanmoqda">☁️ Faqat KT da</span>`;
        }

        // 2. Telegram holati va dinamik progress
        let statusBadge = '';
        let actionBtn = '';
        const stage = s.active_stage || '';
        const percent = s.active_percent || 0;
        const progressText = s.active_text || '';

        if (stage === 'DOWNLOADING_CT') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-retrieving" style="font-size: 0.72rem;">📥 ${progressText || 'KT dan yuklanmoqda: ' + percent + '%'}</span>
                    <div class="progress-track"><div class="progress-fill ct-download" style="width: ${percent}%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-download" disabled>⏳ Yuklanmoqda...</button>`;
        } else if (stage === 'QUEUED_CT') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status" style="background: #fef3c7; color: #b45309; border: 1px solid #fde68a; font-size: 0.74rem; font-weight: 700;">
                        ${progressText || '⏳ KT navbatida (kutilmoqda)'}
                    </span>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm" disabled style="background:#f1f5f9; color:#94a3b8; border:1px solid #cbd5e1;">⏳ Navbatda...</button>`;
        } else if (stage === 'ARCHIVING') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-retrieving" style="font-size: 0.72rem;">🗜️ ZIP qilinmoqda...</span>
                    <div class="progress-track"><div class="progress-fill ct-download" style="width: 95%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-download" disabled>🗜️ Siqilmoqda...</button>`;
        } else if (stage === 'QUEUED_ARCHIVE') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status" style="background: #e0e7ff; color: #4338ca; border: 1px solid #c7d2fe; font-size: 0.74rem; font-weight: 700;">
                        ${progressText || '⏳ ZIP navbatida (kutilmoqda)'}
                    </span>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm" disabled style="background:#f1f5f9; color:#94a3b8; border:1px solid #cbd5e1;">⏳ Navbatda...</button>`;
        } else if (stage === 'UPLOADING_TG') {
            const speedInfo = s.active_speed ? ` • ⚡ ${s.active_speed}` : '';
            const tgText = progressText || `Telegramga: ${percent}%${speedInfo}`;
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-sending" style="font-size: 0.72rem; font-weight: 600;" title="${tgText}">📤 ${tgText}</span>
                    <div class="progress-track"><div class="progress-fill tg-upload" style="width: ${percent}%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-resend" disabled>📤 Yuklanmoqda...</button>`;
        } else if (stage === 'QUEUED_TG') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status" style="background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; font-size: 0.74rem; font-weight: 700;">
                        ${progressText || '⏳ Telegram navbatida (kutilmoqda)'}
                    </span>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm" disabled style="background:#f1f5f9; color:#94a3b8; border:1px solid #cbd5e1;">⏳ Navbatda...</button>`;
        } else if (stage === 'DOWNLOADING_TG') {
            const tgText = progressText || `Telegramdan: ${percent}%`;
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-retrieving" style="font-size: 0.72rem; font-weight: 600;" title="${tgText}">📥 ${tgText}</span>
                    <div class="progress-track"><div class="progress-fill ct-download" style="width: ${percent}%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-download" disabled>📥 Olinmoqda...</button>`;
        } else if (s.telegram_status === 'SENT') {
            statusBadge = '<span class="badge-status status-sent">✅ Yuborildi</span>';
            let btns = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">📤 Telegram</button>`;
            if (!s.has_local_copy && s.telegram_message_id) {
                btns = `<button class="btn btn-sm" onclick="downloadFromTelegram(${s.id})" style="background: #0284c7; color: white; border: none; padding: 4px 8px; font-weight: 600;" title="Telegram kanalidan ZIP arxivni qayta yuklab olish">📥 Telegramdan olish</button> ` + btns;
            }
            if (s.has_local_copy) {
                btns += ` <button class="btn btn-sm" onclick="deleteLocalStorage(${s.id})" style="background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 4px 7px;" title="Serverdagi ZIP arxivni o'chirib diskdan joy bo'shatish">🗑️ O'chirish</button>`;
            }
            actionBtn = btns;
        } else if (s.telegram_status === 'ON_CT_DEVICE') {
            statusBadge = '<span class="badge-status status-on-ct" title="Fayllar KT apparatida">💾 KT Qurilmada</span>';
            actionBtn = `
                <button class="btn btn-sm btn-action-download" onclick="downloadToServer(${s.id})" title="Faqat serverga yuklab olish">📥 Serverga</button>
                <button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})" title="Telegramga yuborish">📤 Telegram</button>
            `;
        } else if (s.telegram_status === 'FAILED') {
            statusBadge = '<span class="badge-status status-failed">❌ Xatolik</span>';
            actionBtn = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">🔄 Qayta urinish</button>`;
        } else {
            statusBadge = '<span class="badge-status status-pending">⏳ Kutilmoqda</span>';
            let btns = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">📤 Telegram</button>`;
            if (s.has_local_copy) {
                btns += ` <button class="btn btn-sm" onclick="deleteLocalStorage(${s.id})" style="background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 4px 7px;" title="Serverdagi ZIP arxivni o'chirib diskdan joy bo'shatish">🗑️ O'chirish</button>`;
            }
            actionBtn = btns;
        }

        return `
        <tr id="study-row-${s.id}" style="${isChecked ? 'background: #eff6ff;' : ''}">
            <td style="text-align: center;">
                <input type="checkbox" class="study-checkbox" value="${s.id}" ${isChecked ? 'checked' : ''} onchange="toggleStudySelect(${s.id}, this)">
            </td>
            <td><strong>${uzDate}</strong> <small style="color:#64748b;">${s.study_time || ''}</small></td>
            <td><code>${s.patient_id || '-'}</code></td>
            <td><strong>${s.patient_name || '-'}</strong></td>
            <td>${s.study_description || '-'}</td>
            <td><strong>${s.instances_count}</strong> kadr</td>
            <td>${storageBadge}</td>
            <td id="status-cell-${s.id}">${statusBadge}</td>
            <td id="action-cell-${s.id}">
                <div class="action-cell-wrapper">
                    ${s.has_local_copy ? `<button class="btn btn-sm btn-action-view" onclick="openInRadiAnt(${s.id})" title="RadiAnt dasturida ochish">🔍 RadiAnt</button>` : ''}
                    ${actionBtn}
                </div>
            </td>
        </tr>
        `;
    }).join('');

    updateSelectedCount();
}

// Barcha tekshiruvlarni serverdan yuklash
async function loadStudies() {
    try {
        const res = await fetch('/api/studies');
        allStudies = await res.json();
        const archCount = document.getElementById('archive-count');
        if (archCount) archCount.innerText = allStudies.length;

        updateFilterCounts();
        populateExamFilterOptions();
        applyStudyFilters();
        checkActiveProgresses();
    } catch (err) {
        console.error("Studies yuklashda xatolik:", err);
    }
}

// Faol progresslarni avtomatik tekshiruvchi funksiya (Live Polling)
async function checkActiveProgresses() {
    try {
        const res = await fetch('/api/studies/progress');
        const progressMap = await res.json();
        const activeIds = Object.keys(progressMap);

        let hasActiveTasks = false;
        const activeStages = ['DOWNLOADING_CT', 'QUEUED_CT', 'ARCHIVING', 'QUEUED_ARCHIVE', 'UPLOADING_TG', 'QUEUED_TG', 'DOWNLOADING_TG'];
        activeIds.forEach(idStr => {
            const id = parseInt(idStr);
            const p = progressMap[idStr];
            if (p && activeStages.includes(p.stage)) {
                hasActiveTasks = true;
                // Mahalliy xotirada mavjud study obyektini yangilash
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.active_stage = p.stage;
                    study.active_percent = p.percent;
                    study.active_text = p.text;
                    study.active_speed = p.speed || '';
                }
            } else if (p && p.stage === 'DONE') {
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.telegram_status = 'SENT';
                    study.active_stage = 'DONE';
                    study.has_local_copy = true;
                }
            } else if (p && p.stage === 'ERROR') {
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.telegram_status = 'FAILED';
                    study.active_stage = 'ERROR';
                    study.active_text = p.text || 'Xatolik';
                }
            }
        });

        updateFilterCounts();

        if (hasActiveTasks) {
            if (currentSortColumn === 'QUEUE_ORDER') {
                applyStudyFilters();
            } else {
                renderStudiesTable();
            }
            if (!activeProgressPollTimer) {
                activeProgressPollTimer = setInterval(checkActiveProgresses, 800);
            }
        } else {
            if (activeProgressPollTimer) {
                clearInterval(activeProgressPollTimer);
                activeProgressPollTimer = null;
                // Yakuniy yangilash
                setTimeout(loadStudies, 1000);
            }
        }
    } catch (e) {
        console.error("Progress tekshirishda xatolik:", e);
    }
}

// KT apparatidagi barcha bemorlarni sinxronlash
async function syncAllCT() {
    const btn = document.getElementById('btn-sync-ct');
    const oldText = btn ? btn.innerText : '';
    if (btn) {
        btn.innerText = "⏳ So'ralmoqda...";
        btn.disabled = true;
    }
    try {
        const res = await fetch('/api/sync_ct', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showDialog({
                title: "KT Sinxronizatsiyasi",
                message: `✅ KT apparatidagi barcha bemorlar muvaffaqiyatli sinxronlandi! Jami: ${data.count} ta tekshiruv.`
            });
            await loadStudies();
        } else {
            showDialog({ title: "Xatolik", message: data.detail || "Sinxronlab bo'lmadi" });
        }
    } catch (err) {
        showDialog({ title: "Tarmoq xatosi", message: err.toString() });
    } finally {
        if (btn) {
            btn.innerText = oldText;
            btn.disabled = false;
        }
    }
}

// Tanlanganlarni bir nechta qilib Telegramga yuborish
async function resendSelectedStudies() {
    if (selectedStudyIds.size === 0) return;

    showDialog({
        title: "Telegramga yuborish",
        message: `${selectedStudyIds.size} ta tekshiruvni Telegram kanaliga yuborishni tasdiqlaysizmi?\n(KT apparatidagi fayllar avtomatik yuklab olinadi va Telegramga yetkaziladi)`,
        confirmText: "Yuborish",
        onConfirm: async () => {
            try {
                const res = await fetch('/api/studies/batch_resend', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ study_ids: Array.from(selectedStudyIds) })
                });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Boshlandi",
                        message: `✅ ${data.count} ta tekshiruv navbatga qo'yildi va yuklash boshlandi!`
                    });
                    selectedStudyIds.clear();
                    const master = document.getElementById('select-all-studies');
                    if (master) master.checked = false;
                    updateSelectedCount();
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuborib bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Tanlanganlarni faqat serverga ZIP qilib arxivlash (Telegramga yubormaydi)
async function archiveSelectedStudies() {
    if (selectedStudyIds.size === 0) return;

    showDialog({
        title: "Serverga Arxivlash",
        message: `${selectedStudyIds.size} ta tekshiruv KT apparatidan ushbu kompyuterga yuklab olinib, ZIP qilib arxivlanadi.\n(Telegramga yuborilmaydi, yuborish tugmasini o'zingiz xohlaganda bosasiz). Tasdiqlaysizmi?`,
        confirmText: "Arxivlashni boshlash",
        onConfirm: async () => {
            try {
                const res = await fetch('/api/studies/batch_archive', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ study_ids: Array.from(selectedStudyIds) })
                });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Arxivlash boshlandi",
                        message: `✅ ${data.count} ta tekshiruv navbatga qo'yildi va orqa fonda yuklanib arxivlanmoqda!`
                    });
                    selectedStudyIds.clear();
                    const master = document.getElementById('select-all-studies');
                    if (master) master.checked = false;
                    updateSelectedCount();
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Arxivlab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Barcha KT apparatidagi tekshiruvlarni serverga to'liq arxivlash
async function archiveAllStudies() {
    showDialog({
        title: "Barcha KT tekshiruvlarini arxivlash",
        message: `KT apparatidagi barcha hali kompyuterda mavjud bo'lmagan bemorlar ketma-ketlikda ushbu kompyuterga yuklab olinadi va ZIP arxivlanadi.\n(Telegramga yuborilmaydi, yuborishni o'zingiz boshqarasiz). Jarayonni boshlaysizmi?`,
        confirmText: "Barchasini arxivlash",
        onConfirm: async () => {
            try {
                const res = await fetch('/api/studies/archive_all_ct', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Ommaviy arxivlash boshlandi",
                        message: `✅ KT apparatidagi ${data.count} ta bemor fonda arxivlash navbatiga qo'yildi!`
                    });
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Boshlab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Barcha faol jarayonlarni bekor qilish va to'xtatish
async function cancelAllOperations() {
    showDialog({
        title: "Barcha jarayonlarni to'xtatish",
        message: "Hozirda orqa fonda bajarilayotgan barcha yuklash, arxivlash va navbatdagi jarayonlarni darhol to'xtatish va tozalashni tasdiqlaysizmi?",
        confirmText: "To'xtatish va tozalash",
        onConfirm: async () => {
            try {
                // UI da darhol barcha faol va navbatdagi holatlarni tozalash
                allStudies.forEach(s => {
                    s.active_stage = 'IDLE';
                    s.active_percent = 0;
                    s.active_text = '';
                    s.active_speed = '';
                    if (s.telegram_status === 'SENDING' || s.telegram_status === 'RETRIEVING') {
                        s.telegram_status = s.has_local_copy ? 'PENDING' : 'ON_CT_DEVICE';
                    }
                });
                renderStudiesTable();
                updateFilterCounts();

                const res = await fetch('/api/queue/cancel_all', { method: 'POST' });
                const data = await res.json();
                showDialog({
                    title: "To'xtatildi",
                    message: "✅ " + (data.message || "Barcha jarayonlar to'xtatildi va holat tozalandi!")
                });
                activeProgressMap = {};
                await loadStudies();
            } catch (err) {
                showDialog({ title: "Xatolik", message: err.toString() });
            }
        }
    });
}

// Bitta bemorni kompyuterdagi ZIP arxivini o'chirish (disk joyini tozalash)
async function deleteLocalStorage(id) {
    const study = allStudies.find(s => s.id === id);
    if (!study) return;

    showDialog({
        title: "Serverdan fayllarni tozalash",
        message: `Ushbu bemorning (${study.patient_name || ''}) kompyuterdagi ZIP arxivi o'chiriladi va diskdan joy bo'shatiladi.\n(KT apparatidagi yoki Telegramdagi nusxasi saqlanib qoladi). Tasdiqlaysizmi?`,
        confirmText: "Diskdan o'chirish",
        onConfirm: async () => {
            try {
                const res = await fetch(`/api/studies/${id}/delete_local`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Tozalandi",
                        message: `✅ ${study.patient_name} fayllari serverdan o'chirildi! (${data.freed_mb || 0} MB bo'shatildi)`
                    });
                    await loadStudies();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "O'chirib bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Tanlangan bemorlarning kompyuterdagi ZIP arxivlarini ommaviy o'chirish
async function deleteSelectedLocalStorage() {
    if (selectedStudyIds.size === 0) return;

    showDialog({
        title: "Tanlanganlarni serverdan tozalash",
        message: `${selectedStudyIds.size} ta tekshiruvning kompyuterdagi mahalliy ZIP arxivi o'chiriladi va diskdan joy bo'shatiladi. Tasdiqlaysizmi?`,
        confirmText: "Barchasini tozalash",
        onConfirm: async () => {
            try {
                const res = await fetch('/api/studies/batch_delete_local', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ study_ids: Array.from(selectedStudyIds) })
                });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Tozalandi",
                        message: `✅ ${data.deleted_count} ta tekshiruv server diskidan tozalandi! (${data.freed_mb || 0} MB bo'shatildi)`
                    });
                    selectedStudyIds.clear();
                    const master = document.getElementById('select-all-studies');
                    if (master) master.checked = false;
                    updateSelectedCount();
                    await loadStudies();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Tozalab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Telegram kanalidan ZIP arxivni kompyuterga qayta yuklab olish
async function downloadFromTelegram(id) {
    const study = allStudies.find(s => s.id === id);
    if (!study) return;

    showDialog({
        title: "Telegramdan yuklab olish",
        message: `Ushbu tekshiruv (${study.patient_name || ''}) Telegram kanalidan kompyuterga qayta yuklab olinadi va arxivlanadi. Boshlaysizmi?`,
        confirmText: "Yuklab olish",
        onConfirm: async () => {
            try {
                study.active_stage = 'DOWNLOADING_TG';
                study.active_percent = 5;
                study.active_text = 'Telegramdan olinmoqda...';
                renderStudiesTable();

                const res = await fetch(`/api/studies/${id}/download_from_telegram`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuklab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Boshqaruv Menyusi (Dropdown) boshqaruvi
function toggleActionDropdown(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('action-dropdown-menu');
    if (menu) menu.classList.toggle('show');
}

function closeActionDropdown() {
    const menu = document.getElementById('action-dropdown-menu');
    if (menu) menu.classList.remove('show');
}

document.addEventListener('click', (e) => {
    const container = document.getElementById('action-dropdown-container');
    if (container && !container.contains(e.target)) {
        closeActionDropdown();
    }
});

// DICOM Import Modal boshqaruvi
let currentImportTab = 'zip';

function openImportModal() {
    const modal = document.getElementById('import-modal');
    if (modal) {
        modal.classList.add('active');
    }
    const inpZip = document.getElementById('import-input-zip');
    const inpFolder = document.getElementById('import-input-folder');
    if (inpZip) inpZip.value = '';
    if (inpFolder) inpFolder.value = '';

    switchImportTab('zip');
    const pArea = document.getElementById('import-progress-area');
    if (pArea) pArea.style.display = 'none';
    const subBtn = document.getElementById('btn-submit-import');
    if (subBtn) {
        subBtn.disabled = false;
        subBtn.innerText = '🚀 Import qilish';
    }
}

function closeImportModal() {
    const modal = document.getElementById('import-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function switchImportTab(tab) {
    currentImportTab = tab;
    const btnZip = document.getElementById('import-tab-zip-btn');
    const btnFolder = document.getElementById('import-tab-folder-btn');
    const panelZip = document.getElementById('import-panel-zip');
    const panelFolder = document.getElementById('import-panel-folder');

    if (tab === 'zip') {
        if (btnZip) btnZip.classList.add('active');
        if (btnFolder) btnFolder.classList.remove('active');
        if (panelZip) panelZip.style.display = 'block';
        if (panelFolder) panelFolder.style.display = 'none';
    } else {
        if (btnFolder) btnFolder.classList.add('active');
        if (btnZip) btnZip.classList.remove('active');
        if (panelFolder) panelFolder.style.display = 'block';
        if (panelZip) panelZip.style.display = 'none';
    }
}

async function startDicomImport() {
    const sendToCt = document.getElementById('import-send-to-ct')?.checked ?? true;
    const pArea = document.getElementById('import-progress-area');
    const pBar = document.getElementById('import-progress-bar');
    const pText = document.getElementById('import-status-text');
    const pPct = document.getElementById('import-percent-text');
    const subBtn = document.getElementById('btn-submit-import');

    const formData = new FormData();
    formData.append('send_to_ct', sendToCt);

    let apiUrl = '';
    if (currentImportTab === 'zip') {
        const fileInput = document.getElementById('import-input-zip');
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            showDialog({ title: "Fayl tanlanmagan", message: "Iltimos, DICOM fayllar joylashgan .ZIP faylni tanlang!" });
            return;
        }
        formData.append('file', fileInput.files[0]);
        apiUrl = '/api/import/zip';
    } else {
        const folderInput = document.getElementById('import-input-folder');
        if (!folderInput || !folderInput.files || folderInput.files.length === 0) {
            showDialog({ title: "Papka tanlanmagan", message: "Iltimos, DICOM fayllar mavjud bo'lgan papkani tanlang!" });
            return;
        }
        for (let i = 0; i < folderInput.files.length; i++) {
            formData.append('files', folderInput.files[i]);
        }
        apiUrl = '/api/import/files';
    }

    if (pArea) pArea.style.display = 'flex';
    if (subBtn) subBtn.disabled = true;
    if (pText) pText.innerText = "Serverga yuklanmoqda...";

    const xhr = new XMLHttpRequest();
    xhr.open('POST', apiUrl, true);

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            if (pBar) pBar.style.width = pct + '%';
            if (pPct) pPct.innerText = pct + '%';
            if (pct >= 100 && pText) {
                pText.innerText = sendToCt 
                    ? "Fayllar qayta ishlanmoqda va KT apparatiga (C-STORE) uzatilmoqda..." 
                    : "Fayllar arxivlanmoqda...";
            }
        }
    };

    xhr.onload = async () => {
        if (xhr.status === 200) {
            try {
                const res = JSON.parse(xhr.responseText);
                closeImportModal();
                let summaryMsg = `✅ ${res.count || 0} ta tekshiruv muvaffaqiyatli import qilindi va mahalliy arxivlandi!`;
                if (res.results && res.results.length > 0) {
                    const r = res.results[0];
                    if (r.sent_to_ct) {
                        summaryMsg += `\n📡 GE KT apparatiga: ${r.ct_sent}/${r.instances_count} kadr uzatildi.`;
                    }
                }
                showDialog({ title: "Import yakunlandi", message: summaryMsg });
                await loadStudies();
            } catch (err) {
                showDialog({ title: "Natija xatosi", message: err.toString() });
            }
        } else {
            let errMsg = "Importda xatolik yuz berdi";
            try {
                const errJson = JSON.parse(xhr.responseText);
                if (errJson.detail) errMsg = errJson.detail;
            } catch (e) {}
            showDialog({ title: "Import xatoligi", message: errMsg });
        }
        if (subBtn) subBtn.disabled = false;
        if (pArea) pArea.style.display = 'none';
    };

    xhr.onerror = () => {
        showDialog({ title: "Tarmoq xatosi", message: "Serverga yuklashda tarmoq xatosi yuz berdi." });
        if (subBtn) subBtn.disabled = false;
        if (pArea) pArea.style.display = 'none';
    };

    xhr.send(formData);
}

// RadiAnt'da ochish
async function openInRadiAnt(id) {
    const study = allStudies.find(s => s.id === id);
    if (study && !study.has_local_copy && study.telegram_status === 'ON_CT_DEVICE') {
        showDialog({
            title: "RadiAnt xabari",
            message: `Ushbu tekshiruv (${study.patient_name || ''}) hozircha faqat KT apparatida saqlanmoqda. Uni avval kompyuterga yuklab olishni xohlaysizmi?`,
            confirmText: "Yuklab olish",
            onConfirm: () => downloadToServer(id)
        });
        return;
    }

    try {
        const res = await fetch(`/api/studies/${id}/open_radiant`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showDialog({
                title: "RadiAnt xabari",
                message: data.detail || "Fayllar topilmadi. Avval '📥 Serverga' tugmasi orqali yuklab oling."
            });
        } else if (data.status === 'fetching') {
            showDialog({
                title: "KT dan olinmoqda",
                message: data.message || "Tekshiruv KT apparatidan yuklanmoqda. Bir ozdan so'ng ochiladi."
            });
        }
    } catch (err) {
        showDialog({ title: "RadiAnt xatosi", message: err.toString() });
    }
}

// Bitta bemorni faqat serverga yuklab olish (Telegramga yubormasdan)
async function downloadToServer(id) {
    const study = allStudies.find(s => s.id === id);
    if (!study) return;

    showDialog({
        title: "Serverga yuklab olish",
        message: `Ushbu tekshiruv (${study.patient_name || ''}) KT apparatidan ushbu kompyuterga yuklab olinadi va arxivlanadi.\n(Telegramga yuborilmaydi)`,
        confirmText: "Yuklab olish",
        onConfirm: async () => {
            try {
                study.active_stage = 'DOWNLOADING_CT';
                study.active_percent = 5;
                study.active_text = 'KT dan olinmoqda...';
                renderStudiesTable();

                const res = await fetch(`/api/studies/${id}/download_to_server`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuklab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Bitta bemorni Telegramga yuborish / KT dan tortish
async function resendTelegram(id) {
    const study = allStudies.find(s => s.id === id);
    const isCt = study && study.telegram_status === 'ON_CT_DEVICE';
    const confirmPrompt = isCt
        ? `Ushbu tekshiruv (${study?.patient_name || ''}) KT apparatidan tortib olinadi va Telegram kanaliga yuboriladi. Davom etasizmi?`
        : `Ushbu tekshiruvni (${study?.patient_name || ''}) Telegram kanaliga yuborishni xohlaysizmi?`;

    showDialog({
        title: "Tasdiqlash",
        message: confirmPrompt,
        confirmText: "Yuborish",
        onConfirm: async () => {
            try {
                // UI da darhol holatni o'zgartirish
                if (study) {
                    study.active_stage = isCt ? 'DOWNLOADING_CT' : 'UPLOADING_TG';
                    study.active_percent = 1;
                    study.active_text = isCt ? 'KT apparatidan olinmoqda...' : 'Telegram serveriga ulanmoqda... 0% • ⚡ 0.0 MB/s';
                    study.active_speed = '0.0 MB/s';
                    renderStudiesTable();
                }

                const res = await fetch(`/api/studies/${id}/resend`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuklab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// -------------------------------------------------------------
// 4. TIZIM VA DICOM LOGLARI
// -------------------------------------------------------------
async function loadLogs() {
    try {
        const res = await fetch('/api/logs?limit=80');
        const logs = await res.json();
        const container = document.getElementById('logs-container');
        if (!container || logs.length === 0) return;

        container.innerHTML = logs.map(l => {
            const time = l.created_at ? l.created_at.replace('T', ' ').substring(11, 19) : '';
            return `
            <div class="log-entry ${l.level}">
                <span style="color: #64748b;">[${time}]</span>
                <strong>[${l.level}]</strong> ${l.message}
            </div>
            `;
        }).join('');
    } catch (err) {
        console.error("Loglar yuklashda xatolik:", err);
    }
}

// -------------------------------------------------------------
// 5. STATUS TEKSHIRUVI VA INISTSIALIZATSIYA
// -------------------------------------------------------------
async function checkSystemStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const ctText = document.getElementById('ct-status-text');
        const ctBadge = document.getElementById('ct-status-badge');
        if (ctBadge && ctText) {
            const dot = ctBadge.querySelector('.dot');
            if (data.ct_online) {
                ctText.innerText = "Ulangan (Online)";
                if (dot) dot.className = "dot green";
            } else {
                ctText.innerText = "Kutilmoqda / Tekshirilmoqda";
                if (dot) dot.className = "dot yellow";
            }
        }

        const diskText = document.getElementById('disk-free-text');
        if (diskText) {
            diskText.innerText = `${data.disk_free_gb} GB (${data.disk_used_percent}% band)`;
        }
    } catch (err) {
        console.error("Status tekshirishda xatolik:", err);
    }
}

// Boshlang'ich yuklash
document.addEventListener('DOMContentLoaded', () => {
    initPreferences();
    checkSystemStatus();
    loadStudies();
    loadLogs();

    setInterval(checkSystemStatus, 15000);
    setInterval(loadLogs, 4000);
});

// -------------------------------------------------------------
// 6. SOZLAMALAR MODAL BOSHQARUVI
// -------------------------------------------------------------
async function openSettingsModal() {
    const backdrop = document.getElementById('settings-modal-backdrop');
    if (!backdrop) return;
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            const cfg = await res.json();
            document.getElementById('setting-ct-host').value = cfg.ct_host || '';
            document.getElementById('setting-ct-port').value = cfg.ct_port || 4006;
            document.getElementById('setting-ct-aet').value = cfg.ct_aet || 'CT01';
            document.getElementById('setting-pacs-port').value = cfg.pacs_port || 11112;
            document.getElementById('setting-pacs-aet').value = cfg.pacs_aet || 'RADIANT';
            document.getElementById('setting-web-port').value = cfg.web_port || 8000;
            document.getElementById('setting-retention-days').value = cfg.retention_days || 30;
            document.getElementById('setting-tg-token').value = cfg.telegram_bot_token || '';
            document.getElementById('setting-tg-channel').value = cfg.telegram_channel_id || '';
            if (document.getElementById('setting-auto-archive')) {
                document.getElementById('setting-auto-archive').checked = cfg.auto_archive_enabled !== false;
            }
            if (document.getElementById('setting-poll-interval')) {
                document.getElementById('setting-poll-interval').value = cfg.new_study_poll_interval || 60;
            }
            if (document.getElementById('setting-stability-checks')) {
                document.getElementById('setting-stability-checks').value = cfg.recon_stability_checks || 3;
            }
            if (document.getElementById('setting-deep-scan')) {
                document.getElementById('setting-deep-scan').value = cfg.deep_scan_interval || 10800;
            }
            if (document.getElementById('setting-batch-conc')) {
                document.getElementById('setting-batch-conc').value = cfg.batch_concurrency || 2;
            }
        }
    } catch (e) {
        console.error("Sozlamalarni olishda xatolik:", e);
    }
    backdrop.classList.add('active');
}

function closeSettingsModal() {
    const backdrop = document.getElementById('settings-modal-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

function handleSettingsBackdropClick(e) {
    if (e.target.id === 'settings-modal-backdrop') {
        closeSettingsModal();
    }
}

async function saveSettingsFromModal() {
    const payload = {
        ct_host: document.getElementById('setting-ct-host').value.trim(),
        ct_port: parseInt(document.getElementById('setting-ct-port').value) || 4006,
        ct_aet: document.getElementById('setting-ct-aet').value.trim() || 'CT01',
        pacs_port: parseInt(document.getElementById('setting-pacs-port').value) || 11112,
        pacs_aet: document.getElementById('setting-pacs-aet').value.trim() || 'RADIANT',
        web_port: parseInt(document.getElementById('setting-web-port').value) || 8000,
        retention_days: parseInt(document.getElementById('setting-retention-days').value) || 30,
        telegram_bot_token: document.getElementById('setting-tg-token').value.trim(),
        telegram_channel_id: document.getElementById('setting-tg-channel').value.trim(),
        auto_archive_enabled: document.getElementById('setting-auto-archive') ? document.getElementById('setting-auto-archive').checked : true,
        new_study_poll_interval: parseInt(document.getElementById('setting-poll-interval')?.value) || 60,
        recon_stability_checks: parseInt(document.getElementById('setting-stability-checks')?.value) || 3,
        deep_scan_interval: parseInt(document.getElementById('setting-deep-scan')?.value) || 10800,
        batch_concurrency: parseInt(document.getElementById('setting-batch-conc')?.value) || 2
    };

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            closeSettingsModal();
            showDialog({
                title: "Saqlandi",
                message: "✅ Sozlamalar muvaffaqiyatli saqlandi va qo'llanildi!"
            });
            checkSystemStatus();
        } else {
            const err = await res.json();
            showDialog({ title: "Xatolik", message: err.detail || "Saqlab bo'lmadi" });
        }
    } catch (e) {
        showDialog({ title: "Xatolik", message: e.toString() });
    }
}
