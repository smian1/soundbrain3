// At the beginning of app.js
console.log('io function:', io); // Should not be undefined

// Initialize Socket.IO
const socket = io();

socket.on('connect', () => {
    console.log('Socket.IO connected');
});



// Extend Day.js with plugins
dayjs.extend(window.dayjs_plugin_utc);
dayjs.extend(window.dayjs_plugin_timezone);

// Global variables
let currentPage = 1;
let summariesCurrentPage = 1;
let currentSpeaker = null;
let currentMessageBlock = null;
let lastTimestamp = null;
let currentSelectedDate = null;
let currentSelectedHour = null;
let liveTranscriptionContent;
let currentTranscriptSpeaker = null;
let currentTranscriptBlock = null;

let lastSpeaker = null;
const TIME_GAP_THRESHOLD = 60000; // 1 minute in milliseconds

const itemsPerPage = 100;
const speakerColors = {
    'SPEAKER_01': '#8B5CF6', // Purple
    'SPEAKER_02': '#3B82F6', // Blue
    'SPEAKER_03': '#10B981', // Green
    // Add more speakers and colors as needed
};

const SENTENCE_END_REGEX = /[.!?]\s*$/;
const FILLER_WORDS_REGEX = /\b(um|uh|like|you know|I mean)\b/gi;

// Modify these global variables
let speakerBuffers = {};
let lastSpeakerTimestamp = {};
const LIVE_MERGE_THRESHOLD = 3000; // 3 seconds
const WORD_PAUSE_THRESHOLD = 1000; // 1 second pause between words

// Add these new variables
let currentLiveSpeaker = null;
let currentLiveMessageElement = null;
let liveTranscriptionBuffer = '';
let displayedText = '';
const BUFFER_UPDATE_INTERVAL = 1000; // 1 second

let currentActiveTab = 'liveTranscriptionTab';
let currentDate = dayjs();

// Utility functions
const utils = {
    formatDate: function(date) {
        return dayjs(date).format('MMMM D, YYYY');
    },
    updateCurrentDate: function(date) {
        const formattedDate = this.formatDate(date);
        document.getElementById('currentDate').textContent = formattedDate;
        const flatpickrInstance = document.querySelector("#calendar")._flatpickr;
        if (flatpickrInstance) {
            flatpickrInstance.setDate(dayjs(date).toDate(), false);
        }
    },
    getCurrentDate: function() {
        return dayjs().format('YYYY-MM-DD');
    },
    formatHourRange: function(hour) {
        const startHour = hour % 12 || 12;
        const endHour = (hour + 1) % 12 || 12;
        const startAMPM = hour < 12 ? 'AM' : 'PM';
        const endAMPM = hour < 11 ? startAMPM : (startAMPM === 'AM' ? 'PM' : 'AM');
        return `${startHour}:00 ${startAMPM} - ${endHour}:00 ${endAMPM}`;
    },
    updateHourIndicator: function(hour) {
        const hourIndicator = document.getElementById('hourIndicator');
        const displayHour = hour % 12 || 12;
        const ampm = hour < 12 ? 'a' : 'p';
        hourIndicator.textContent = `${displayHour}${ampm}`;
        const percent = (hour / 23) * 100;
        hourIndicator.style.left = `${percent}%`;
    }
};

// Function definitions
function fetchTranscripts(date, page = 1, hour = null) {
    const loadingIndicator = document.getElementById('loadingIndicator');
    loadingIndicator.classList.remove('hidden');

    let url = `/get_transcripts?date=${date}&page=${page}`;
    if (hour !== null) {
        url += `&hour=${hour}`;
    }

    fetch(url)
        .then(response => response.json())
        .then(data => {
            const transcriptsList = document.getElementById('transcriptsList');
            transcriptsList.innerHTML = '';
            
            // Combine segments from the same speaker
            let combinedSegments = [];
            let currentSpeaker = null;
            let currentSegment = null;

            data.segments.forEach(segment => {
                if (segment.speaker !== currentSpeaker) {
                    if (currentSegment) {
                        combinedSegments.push(currentSegment);
                    }
                    currentSpeaker = segment.speaker;
                    currentSegment = { ...segment };
                } else {
                    currentSegment.text += ' ' + segment.text;
                }
            });
            if (currentSegment) {
                combinedSegments.push(currentSegment);
            }

            combinedSegments.forEach(segment => {
                const segmentElement = createSegmentElement(segment);
                transcriptsList.appendChild(segmentElement);
            });

            updatePagination(data.current_page, data.total_pages);
            loadingIndicator.classList.add('hidden');
        })
        .catch(error => {
            console.error('Error fetching transcripts:', error);
            loadingIndicator.classList.add('hidden');
        });
}

function fetchSummaries(page, date) {
    document.getElementById('summariesList').innerHTML = '';
    document.getElementById('summariesPaginationControls').classList.add('hidden');

    if (!date) {
        date = utils.getCurrentDate();
    }

    fetch(`/get_summaries?date=${date}&page=${page}&per_page=${itemsPerPage}`)
        .then(response => response.json())
        .then(data => {
            if (data.summaries && data.summaries.length > 0) {
                data.summaries.forEach(summary => {
                    addSummaryToList(summary);
                });
                updateSummariesPaginationControls(data.total_pages, data.current_page);
                document.getElementById('summariesPaginationControls').classList.remove('hidden');
            } else {
                document.getElementById('summariesList').innerHTML = '<p>No summaries found for this date.</p>';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('summariesList').innerHTML = '<p>Error loading summaries. Please try again later.</p>';
        });
}

function fetchDashboardData(date) {
    Promise.all([
        fetch(`/get_heatmap_data?date=${date}`).then(response => response.json()),
        fetch(`/get_word_cloud_data?date=${date}`).then(response => response.json()),
        fetch(`/get_dashboard_stats?date=${date}`).then(response => response.json())
    ]).then(([heatmapData, wordCloudData, dashboardStats]) => {
        renderHeatmap(heatmapData);
        renderWordCloud(wordCloudData);
        renderDashboardStats(dashboardStats);
    }).catch(error => {
        console.error('Error fetching dashboard data:', error);
        // Handle the error appropriately, e.g., display an error message to the user
    });
}

function addMessage(data) {
    console.log("Processing segment:", data);
    if (!liveTranscriptionContent) {
        console.error('Live transcription content element not found');
        return;
    }
    const timestamp = dayjs.utc(data.timestamp).local();
    console.log("Processed timestamp:", timestamp.format());
    
    if (data.speaker !== currentSpeaker || !lastTimestamp || timestamp.diff(lastTimestamp, 'minute') > 1) {
        currentSpeaker = data.speaker;
        currentMessageBlock = document.createElement('div');
        currentMessageBlock.className = 'mb-4 p-3 rounded-lg';
        
        const speakerColor = speakerColors[data.speaker] || '#6B7280';
        currentMessageBlock.style.backgroundColor = `${speakerColor}10`;
        
        currentMessageBlock.innerHTML = `
            <div class="flex items-center mb-2">
                <div class="px-3 py-1 rounded-full text-white text-sm font-bold" style="background-color: ${speakerColor};">
                    ${data.speaker}
                </div>
                <div class="text-xs text-gray-500 ml-2">${timestamp.format('h:mm A')}</div>
            </div>
            <div class="text-gray-800 message-content">${data.text}</div>
        `;
        liveTranscriptionContent.appendChild(currentMessageBlock);
    } else if (currentMessageBlock) {
        const messageContent = currentMessageBlock.querySelector('.message-content');
        messageContent.innerHTML += ' ' + data.text;
    }
    lastTimestamp = timestamp;
    liveTranscriptionContent.scrollTop = liveTranscriptionContent.scrollHeight;
    console.log("Message added to live transcription");
}

function addMessageToTranscripts(segment) {
    const transcriptsList = document.getElementById('transcriptsList');
    const timestamp = dayjs.utc(segment.timestamp).local();
    
    const showNewGroup = segment.speaker !== lastSpeaker || 
                         (lastTimestamp && timestamp.diff(lastTimestamp) > TIME_GAP_THRESHOLD);

    if (showNewGroup) {
        currentTranscriptBlock = createNewTranscriptBlock(segment, timestamp);
        transcriptsList.appendChild(currentTranscriptBlock);
    } else {
        appendToExistingTranscriptBlock(segment, timestamp);
    }

    lastSpeaker = segment.speaker;
    lastTimestamp = timestamp;
}

function createNewTranscriptBlock(segment, timestamp) {
    const messageElement = document.createElement('div');
    messageElement.className = 'mb-4 p-3 rounded-lg';
    
    const speakerColor = speakerColors[segment.speaker] || '#6B7280';
    messageElement.style.backgroundColor = `${speakerColor}10`;
    
    const cleanedText = cleanAndFormatText(segment.text);
    
    messageElement.innerHTML = `
        <div class="flex items-center mb-2">
            <div class="px-3 py-1 rounded-full text-white text-sm font-bold" style="background-color: ${speakerColor};">
                ${segment.speaker}
            </div>
            <div class="text-xs text-gray-500 ml-2">${timestamp.format('h:mm A')}</div>
        </div>
        <div class="text-gray-800 message-content">
            ${cleanedText}
        </div>
    `;
    return messageElement;
}

function appendToExistingTranscriptBlock(segment, timestamp) {
    if (currentTranscriptBlock) {
        const messageContent = currentTranscriptBlock.querySelector('.message-content');
        const cleanedText = cleanAndFormatText(segment.text);
        
        // Check if the last character of the existing content is a space
        const lastChar = messageContent.innerHTML.slice(-1);
        const spacer = lastChar === ' ' ? '' : ' ';
        
        messageContent.innerHTML += spacer + cleanedText;
    }
}

function addSummaryToList(summary) {
    const summariesList = document.getElementById('summariesList');
    const summaryElement = document.createElement('div');
    summaryElement.className = 'mb-4 p-4 bg-white rounded-lg shadow';
    
    const timestamp = dayjs.utc(summary.timestamp).local();
    
    summaryElement.innerHTML = `
        <h3 class="text-lg font-semibold mb-2">${summary.headline}</h3>
        <p class="text-sm text-gray-500 mb-2">${timestamp.format('MMMM D, YYYY h:mm A')}</p>
        <ul class="list-disc list-inside mb-2">
            ${summary.bullet_points.map(point => `<li>${point}</li>`).join('')}
        </ul>
        <p class="text-sm"><strong>Tag:</strong> ${summary.tag}</p>
        <p class="text-sm"><strong>Fact Check:</strong> ${summary.fact_checker}</p>
    `;
    summariesList.appendChild(summaryElement);
}

function renderHeatmap(data) {
    const canvas = document.getElementById('heatmapChart');
    if (!canvas) {
        console.error('Heatmap canvas not found');
        return;
    }
    const ctx = canvas.getContext('2d');
    
    // Destroy existing chart if it exists
    if (window.heatmapChart && typeof window.heatmapChart.destroy === 'function') {
        window.heatmapChart.destroy();
    }

    window.heatmapChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: Array.from({length: 24}, (_, i) => {
                const hour = i % 12 || 12;
                const ampm = i < 12 ? 'AM' : 'PM';
                return `${hour}${ampm}`;
            }),
            datasets: [{
                label: 'Conversation Segments',
                data: data,
                backgroundColor: data.map(value => `rgba(139, 92, 246, ${value / Math.max(...data)})`),
                borderColor: 'rgba(139, 92, 246, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Number of Segments'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Hour of Day (Pacific Time)'
                    }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `Segments: ${context.raw}`;
                        }
                    }
                }
            }
        }
    });
}

function renderWordCloud(data) {
    const width = document.getElementById('wordCloudContainer').offsetWidth;
    const height = document.getElementById('wordCloudContainer').offsetHeight;

    d3.select("#wordCloudContainer").selectAll("*").remove();

    const layout = d3.layout.cloud()
        .size([width, height])
        .words(data)
        .padding(5)
        .rotate(() => ~~(Math.random() * 2) * 90)
        .font("Inter")
        .fontSize(d => Math.sqrt(d.value) * 5)
        .on("end", draw);

    layout.start();

    function draw(words) {
        d3.select("#wordCloudContainer").append("svg")
            .attr("width", layout.size()[0])
            .attr("height", layout.size()[1])
            .append("g")
            .attr("transform", `translate(${layout.size()[0] / 2},${layout.size()[1] / 2})`)
            .selectAll("text")
            .data(words)
            .enter().append("text")
            .style("font-size", d => `${d.size}px`)
            .style("font-family", "Inter")
            .style("fill", () => d3.schemeCategory10[Math.floor(Math.random() * 10)])
            .attr("text-anchor", "middle")
            .attr("transform", d => `translate(${d.x},${d.y})rotate(${d.rotate})`)
            .text(d => d.text);
    }
}

function renderDashboardStats(stats) {
    const mostActiveHourElement = document.getElementById('mostActiveHour');
    const totalSegmentsElement = document.getElementById('totalSegments');

    if (stats.most_active_hour !== null) {
        const hour = stats.most_active_hour % 12 || 12;
        const ampm = stats.most_active_hour < 12 ? 'AM' : 'PM';
        mostActiveHourElement.textContent = `${hour}:00 ${ampm}`;
    } else {
        mostActiveHourElement.textContent = 'N/A';
    }

    totalSegmentsElement.textContent = stats.total_segments;
}

function updatePaginationControls(totalPages, currentPage) {
    document.getElementById('pageInfo').textContent = `Page ${currentPage} of ${totalPages}`;
    document.getElementById('prevPage').disabled = currentPage === 1;
    document.getElementById('nextPage').disabled = currentPage === totalPages;
}

function updateSummariesPaginationControls(totalPages, currentPage) {
    document.getElementById('summariesPageInfo').textContent = `Page ${currentPage} of ${totalPages}`;
    document.getElementById('summariesPrevPage').disabled = currentPage === 1;
    document.getElementById('summariesNextPage').disabled = currentPage === totalPages;
}

function fetchTranscriptsForHour(hour) {
    currentSelectedHour = hour;
    currentPage = 1; // Reset to first page when changing hour
    fetchTranscripts(currentSelectedDate, currentPage, hour);
    utils.updateHourIndicator(hour);
    document.getElementById('selectedHour').textContent = `Transcripts for ${utils.formatHourRange(hour)}`;
    
    // Update the time slider
    const timeSlider = document.getElementById('timeSlider');
    timeSlider.value = hour;
}

function switchTab(tabId) {
    const tabs = ['liveTranscriptionTab', 'transcriptsTab', 'dashboardTab', 'summariesTab'];
    tabs.forEach(tab => {
        const element = document.getElementById(tab);
        const content = document.getElementById(tab.replace('Tab', 'Content'));
        if (tab === tabId) {
            element.classList.add('tab-active');
            element.classList.remove('tab-inactive');
            content.classList.remove('hidden');
        } else {
            element.classList.remove('tab-active');
            element.classList.add('tab-inactive');
            content.classList.add('hidden');
        }
    });
    currentActiveTab = tabId;
    
    if (tabId === 'transcriptsTab') {
        document.getElementById('timeSelectionBar').classList.remove('hidden');
        initializeTimeSlider();
        currentSelectedHour = getCurrentHour(); // Set the current hour
        fetchTranscriptsForHour(currentSelectedHour);
    } else {
        document.getElementById('timeSelectionBar').classList.add('hidden');
    }
    
    if (tabId === 'dashboardTab') {
        updateContentForDate(currentDate);
    } else {
        updateContentForDate(currentDate);
    }
}

function updateContentForDate(date) {
    if (!(date instanceof dayjs)) {
        date = dayjs(date);
    }
    
    const formattedDate = date.format('YYYY-MM-DD');
    document.getElementById('currentDate').textContent = date.format('MMMM D, YYYY');

    if (currentActiveTab === 'liveTranscriptionTab') {
        // Update live transcription content (if needed)
    } else if (currentActiveTab === 'transcriptsTab') {
        fetchTranscripts(formattedDate, 1, currentSelectedHour);
    } else if (currentActiveTab === 'dashboardTab') {
        fetchDashboardData(formattedDate);
    } else if (currentActiveTab === 'summariesTab') {
        loadSummariesForDate(date);
    }
}

function loadSummariesForDate(date) {
    const formattedDate = date.format('YYYY-MM-DD');
    fetch(`/get_summaries?date=${formattedDate}`)
        .then(response => response.json())
        .then(data => {
            console.log('Received summaries data:', data);  // Log the received data
            if (Array.isArray(data.summaries)) {
                renderSummaries(data.summaries);
                updatePagination(data.current_page, data.total_pages, 'summaries');
            } else {
                console.error('Received invalid summaries data:', data);
                document.getElementById('summariesList').innerHTML = '<p>No summaries available for this date.</p>';
            }
        })
        .catch(error => {
            console.error('Error loading summaries:', error);
            document.getElementById('summariesList').innerHTML = '<p>Error loading summaries. Please try again later.</p>';
        });
}

function renderSummaries(summaries) {
    const summariesList = document.getElementById('summariesList');
    summariesList.innerHTML = '';

    summaries.forEach((summary) => {
        const summaryItem = document.createElement('div');
        summaryItem.className = 'bg-white rounded-lg shadow-md p-4 mb-4 relative group'; // Added 'relative' and 'group' classes

        const time = dayjs(summary.timestamp).format('MMMM D, YYYY h:mm A');

        let factCheckerHTML = '';
        if (summary.fact_checker) {
            let factCheckerContent = '';
            if (typeof summary.fact_checker === 'string' && summary.fact_checker.trim() !== '') {
                factCheckerContent = summary.fact_checker;
            } else if (Array.isArray(summary.fact_checker) && summary.fact_checker.length > 0) {
                factCheckerContent = summary.fact_checker.join('<br>');
            }

            if (factCheckerContent) {
                factCheckerHTML = `
                    <div class="bg-red-50 border border-red-200 rounded p-3 mt-3">
                        <p class="text-red-700 font-semibold mb-1">⚠️ Fact Checker</p>
                        <p class="text-red-600 text-sm">${factCheckerContent}</p>
                    </div>
                `;
            }
        }

        summaryItem.innerHTML = `
            <div class="flex items-center justify-between mb-2">
                <h3 class="text-lg font-semibold">${summary.headline}</h3>
                <span class="px-3 py-1 bg-blue-100 text-blue-800 text-xs font-semibold rounded-full uppercase">${summary.tag}</span>
            </div>
            <p class="text-gray-500 text-sm mb-2">${time}</p>
            <ul class="list-disc pl-5 text-gray-700">
                ${Array.isArray(summary.bullet_points) 
                    ? summary.bullet_points.map(item => `<li>${item}</li>`).join('') 
                    : summary.bullet_points.split('\n').map(item => `<li>${item.trim().substring(2)}</li>`).join('')}
            </ul>
            ${factCheckerHTML}
        `;

        // Add the three dots
        const dotsButton = document.createElement('div');
        dotsButton.className = 'absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200';
        dotsButton.innerHTML = `
            <button class="view-transcripts text-gray-500 hover:text-gray-700" data-summary-id="${summary.id}">
                <i class="fas fa-ellipsis-h"></i>
            </button>
        `;

        summaryItem.appendChild(dotsButton);
        summariesList.appendChild(summaryItem);
    });

    // Set up event listeners for the new buttons
    setupTranscriptViewers();
}

function initializeFlatpickr() {
    flatpickr("#calendar", {
        inline: true,
        defaultDate: dayjs().format('YYYY-MM-DD'),
        onChange: function(selectedDates, dateStr, instance) {
            if (selectedDates.length > 0) {
                currentDate = dayjs(selectedDates[0]);
                updateContentForDate(currentDate);
            }
        }
    });
}

function populateTimeline() {
    initializeTimeSlider();
}

function initializeTimeSlider() {
    const timeSlider = document.getElementById('timeSlider');
    const hourIndicator = document.getElementById('hourIndicator');

    // Set initial value to current hour
    const currentHour = getCurrentHour();
    timeSlider.value = currentHour;
    utils.updateHourIndicator(currentHour);

    timeSlider.addEventListener('input', function() {
        const hour = parseInt(this.value);
        utils.updateHourIndicator(hour);
    });

    timeSlider.addEventListener('change', function() {
        const hour = parseInt(this.value);
        fetchTranscriptsForHour(hour);
    });
}

function showSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function hideSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.add('hidden');
    document.body.style.overflow = '';
}

function handleResize() {
    const sidebar = document.getElementById('sidebar');
    const showCalendarBtn = document.getElementById('showCalendarBtn');
    
    if (window.innerWidth >= 768) { // Desktop view
        sidebar.classList.remove('hidden', 'fixed', 'inset-0', 'z-50');
        sidebar.classList.add('md:block');
        showCalendarBtn.classList.add('hidden');
        document.body.style.overflow = '';
    } else { // Mobile view
        sidebar.classList.add('hidden');
        sidebar.classList.remove('md:block');
        showCalendarBtn.classList.remove('hidden');
    }
}

function initializeApp() {
    initializeFlatpickr();
    currentSelectedDate = utils.getCurrentDate();
    utils.updateCurrentDate(dayjs(currentSelectedDate));
    switchTab('liveTranscriptionTab');
    updateContentForDate(currentDate);
}

// Expose necessary functions globally
window.fetchTranscripts = fetchTranscripts;
window.fetchSummaries = fetchSummaries;
window.fetchDashboardData = fetchDashboardData;
window.addMessage = addMessage;
window.initializeApp = initializeApp;

// DOM-ready event listener
document.addEventListener('DOMContentLoaded', function() {
    liveTranscriptionContent = document.getElementById('liveTranscriptionContent');
    if (!liveTranscriptionContent) {
        console.error('Live transcription content element not found');
    }

    // Initialize Socket.IO
    const socket = io();

    socket.on('connect', () => {
        console.log('Socket.IO connected');
    });

    socket.on('disconnect', () => {
        console.log('Socket.IO disconnected');
    });

    socket.on('error', (error) => {
        console.error('Socket.IO error:', error);
    });

    // Listen for 'new_segment' event
    socket.on('new_segment', (data) => {
        console.log('Received new segment:', data);
        processLiveTranscription(data);
        return false;
    });

    initializeApp();

    // Event listeners
    
    document.getElementById('liveTranscriptionTab').addEventListener('click', () => switchTab('liveTranscriptionTab'));
    document.getElementById('transcriptsTab').addEventListener('click', () => switchTab('transcriptsTab'));
    document.getElementById('dashboardTab').addEventListener('click', () => switchTab('dashboardTab'));
    document.getElementById('summariesTab').addEventListener('click', () => switchTab('summariesTab'));

    document.getElementById('showCalendarBtn').addEventListener('click', showSidebar);
    document.getElementById('closeSidebarBtn').addEventListener('click', hideSidebar);
    document.getElementById('mobileMenuToggle').addEventListener('click', function() {
        const nav = document.querySelector('header nav');
        nav.classList.toggle('hidden');
    });

    document.getElementById('prevPage').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            fetchTranscripts(currentSelectedDate, currentPage, currentSelectedHour);
        }
    });

    document.getElementById('nextPage').addEventListener('click', () => {
        currentPage++;
        fetchTranscripts(currentSelectedDate, currentPage, currentSelectedHour);
    });

    document.getElementById('summariesPrevPage').addEventListener('click', () => {
        if (summariesCurrentPage > 1) {
            summariesCurrentPage--;
            fetchSummaries(summariesCurrentPage, currentSelectedDate);
        }
    });

    document.getElementById('summariesNextPage').addEventListener('click', () => {
        summariesCurrentPage++;
        fetchSummaries(summariesCurrentPage, currentSelectedDate);
    });

    document.getElementById('prevDate').addEventListener('click', function() {
        currentDate = currentDate.subtract(1, 'day');
        updateContentForDate(currentDate);
    });

    document.getElementById('nextDate').addEventListener('click', function() {
        currentDate = currentDate.add(1, 'day');
        updateContentForDate(currentDate);
    });

    handleResize();

    // Start the buffer update loop
    updateLiveTranscriptionBuffer();

    // Add this near the top of the file, after other event listeners
    setupTranscriptViewers();

    // If you're loading summaries on page load, make sure to call setupTranscriptViewers after that
    loadSummariesForDate(currentDate).then(() => {
        setupTranscriptViewers();
    });
});

// Window resize event listener
window.addEventListener('resize', handleResize);

// Process existing segments
console.log("Existing segments:", window.existingSegments);
if (window.existingSegments && window.existingSegments.length > 0) {
    window.existingSegments.forEach(segment => {
        addMessage(segment);
    });
    console.log("Processed existing segments");
} else {
    console.log("No existing segments found");
}

// Make sure all asynchronous operations are properly handled
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

function cleanAndFormatText(text) {
    // Remove consecutive spaces and trim
    let cleanedText = text.replace(/\s+/g, ' ').trim();
    
    // Capitalize the first letter of the text
    cleanedText = cleanedText.charAt(0).toUpperCase() + cleanedText.slice(1);
    
    // Ensure the text ends with proper punctuation if it's a complete sentence
    if (SENTENCE_END_REGEX.test(cleanedText)) {
        const sentences = cleanedText.match(/[^.!?]+[.!?]+/g) || [];
        cleanedText = sentences.map(sentence => sentence.trim()).join(' ');
    }
    
    return cleanedText;
}

function mergeCloseSegments(segments) {
    const mergedSegments = [];
    let currentSegment = null;

    for (const segment of segments) {
        if (!currentSegment) {
            currentSegment = { ...segment };
        } else if (segment.speaker === currentSegment.speaker &&
                   dayjs(segment.timestamp).diff(dayjs(currentSegment.timestamp)) < TIME_GAP_THRESHOLD) {
            currentSegment.text += ' ' + segment.text.trim();
        } else {
            currentSegment.text = cleanAndFormatText(currentSegment.text);
            mergedSegments.push(currentSegment);
            currentSegment = { ...segment };
        }
    }

    if (currentSegment) {
        currentSegment.text = cleanAndFormatText(currentSegment.text);
        mergedSegments.push(currentSegment);
    }

    return mergedSegments;
}

// Add these new functions
function processLiveTranscription(data) {
    const { speaker, text, timestamp } = data;
    
    if (speaker !== currentLiveSpeaker) {
        flushLiveTranscriptionBuffer();
        currentLiveSpeaker = speaker;
        currentLiveMessageElement = createNewLiveMessageElement(speaker, timestamp);
        liveTranscriptionContent.appendChild(currentLiveMessageElement);
        liveTranscriptionBuffer = '';
        displayedText = '';
    }
    
    appendToLiveTranscription(text);
}

function createNewLiveMessageElement(speaker, timestamp) {
    const messageElement = document.createElement('div');
    messageElement.className = 'mb-4 p-3 rounded-lg';
    
    const speakerColor = speakerColors[speaker] || '#6B7280';
    messageElement.style.backgroundColor = `${speakerColor}10`;
    
    messageElement.innerHTML = `
        <div class="flex items-center mb-2">
            <div class="px-3 py-1 rounded-full text-white text-sm font-bold" style="background-color: ${speakerColor};">
                ${speaker}
            </div>
            <div class="text-xs text-gray-500 ml-2">${dayjs(timestamp).format('h:mm A')}</div>
        </div>
        <div class="text-gray-800 message-content"></div>
    `;
    return messageElement;
}

function appendToLiveTranscription(text) {
    if (currentLiveMessageElement) {
        const messageContent = currentLiveMessageElement.querySelector('.message-content');
        liveTranscriptionBuffer += text + ' ';
        
        // Only add new text to the displayed text
        const newText = liveTranscriptionBuffer.slice(displayedText.length);
        displayedText += newText;
        
        // Append only the new text
        messageContent.textContent += newText;
    }
    liveTranscriptionContent.scrollTop = liveTranscriptionContent.scrollHeight;
}

function flushLiveTranscriptionBuffer() {
    if (currentLiveMessageElement && liveTranscriptionBuffer) {
        const messageContent = currentLiveMessageElement.querySelector('.message-content');
        const cleanedText = cleanAndFormatText(liveTranscriptionBuffer);
        
        // Only update if there are changes
        if (messageContent.textContent !== cleanedText) {
            messageContent.textContent = cleanedText;
        }
        
        displayedText = cleanedText;
        liveTranscriptionBuffer = cleanedText;
    }
}

function updateLiveTranscriptionBuffer() {
    flushLiveTranscriptionBuffer();
    setTimeout(updateLiveTranscriptionBuffer, BUFFER_UPDATE_INTERVAL);
}

// Add this function to your app.js file
function updatePagination(currentPage, totalPages) {
    const pageInfo = document.getElementById('pageInfo');
    const prevButton = document.getElementById('prevPage');
    const nextButton = document.getElementById('nextPage');

    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
    prevButton.disabled = currentPage === 1;
    nextButton.disabled = currentPage === totalPages;

    const paginationControls = document.getElementById('paginationControls');
    paginationControls.classList.toggle('hidden', totalPages <= 1);
}

// Make sure to call this function when loading transcripts
// For example, in your loadTranscripts function:
function loadTranscripts(date, hour) {
    // ... existing code ...

    // After loading and displaying transcripts
    updatePagination(currentPage, totalPages);
}

function removeEmojis(str) {
    return str.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}]/gu, '').trim();
}

function createSummaryHTML(summary) {
    const sanitizedSubject = removeEmojis(summary.subject);
    
    // Use sanitizedSubject instead of summary.subject in your HTML
    return `
        <div class="summary-item">
            <div class="summary-header">
                <h3 class="summary-subject">${sanitizedSubject}</h3>
                <!-- ... rest of the HTML ... -->
            </div>
            <!-- ... rest of the summary HTML ... -->
        </div>
    `;
}

// Add this function to initialize the time selection bar
function initializeTimeSelectionBar() {
    const timeSlider = document.getElementById('timeSlider');
    const hourIndicator = document.getElementById('hourIndicator');
    const selectedHour = document.getElementById('selectedHour');

    timeSlider.addEventListener('input', function() {
        const hour = parseInt(this.value);
        const displayHour = hour === 0 ? '12 AM' : hour < 12 ? `${hour} AM` : hour === 12 ? '12 PM' : `${hour - 12} PM`;
        hourIndicator.textContent = displayHour;
        hourIndicator.style.left = `${(hour / 23) * 100}%`;
        selectedHour.textContent = `Showing transcripts for ${displayHour}`;
        fetchTranscripts(currentDate, 1, hour);
    });
}

// Update the showTranscriptsTab function to show the time selection bar
function showTranscriptsTab() {
    // ... (existing code) ...
    document.getElementById('timeSelectionBar').classList.remove('hidden');
    initializeTimeSelectionBar();
    fetchTranscripts(currentDate);
}

// Update the hideAllTabs function to hide the time selection bar
function hideAllTabs() {
    // ... (existing code) ...
    document.getElementById('timeSelectionBar').classList.add('hidden');
}

function createSegmentElement(segment) {
    const segmentElement = document.createElement('div');
    segmentElement.className = 'mb-4 p-3 rounded-lg';
    
    const speakerColor = speakerColors[segment.speaker] || '#6B7280';
    segmentElement.style.backgroundColor = `${speakerColor}10`;
    
    const timestamp = dayjs.utc(segment.timestamp).local();
    
    segmentElement.innerHTML = `
        <div class="flex items-center mb-2">
            <div class="px-3 py-1 rounded-full text-white text-sm font-bold" style="background-color: ${speakerColor};">
                ${segment.speaker}
            </div>
            <div class="text-xs text-gray-500 ml-2">${timestamp.format('h:mm A')}</div>
        </div>
        <div class="text-gray-800 message-content">${cleanAndFormatText(segment.text)}</div>
    `;
    
    return segmentElement;
}

// Add this function to get the current hour
function getCurrentHour() {
    return dayjs().hour();
}

// Add this near the top of the file, after other event listeners
document.addEventListener('DOMContentLoaded', function() {
    setupTranscriptViewers();
});

function setupTranscriptViewers() {
    const viewTranscriptsBtns = document.querySelectorAll('.view-transcripts');
    const modal = document.getElementById('transcriptModal');
    const modalContent = document.getElementById('modalContent');
    const closeModal = document.getElementById('closeModal');

    viewTranscriptsBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const summaryId = this.getAttribute('data-summary-id');
            fetchAndDisplayTranscripts(summaryId);
        });
    });

    if (closeModal) {
        closeModal.addEventListener('click', function() {
            modal.classList.add('hidden');
        });
    }
}

function fetchAndDisplayTranscripts(summaryId) {
    const modal = document.getElementById('transcriptModal');
    const modalContent = document.getElementById('modalContent');
    modalContent.innerHTML = '<p class="text-center">Loading transcripts...</p>';
    modal.classList.remove('hidden');

    fetch(`/get_summary_transcripts/${summaryId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                modalContent.innerHTML = `<p class="text-red-500">${data.error}</p>`;
            } else {
                let currentSpeaker = null;
                let transcriptHtml = '';

                data.forEach(segment => {
                    if (segment.speaker !== currentSpeaker) {
                        if (currentSpeaker !== null) {
                            transcriptHtml += '</div>';
                        }
                        currentSpeaker = segment.speaker;
                        const speakerColor = speakerColors[segment.speaker] || '#6B7280';
                        transcriptHtml += `
                            <div class="mb-4">
                                <div class="flex items-center mb-2">
                                    <div class="px-3 py-1 rounded-full text-white text-sm font-bold" style="background-color: ${speakerColor};">
                                        ${segment.speaker}
                                    </div>
                                    <div class="text-xs text-gray-500 ml-2">${new Date(segment.timestamp).toLocaleTimeString()}</div>
                                </div>
                                <div class="pl-4 text-gray-800">
                        `;
                    }
                    transcriptHtml += `${segment.text} `;
                });

                if (currentSpeaker !== null) {
                    transcriptHtml += '</div></div>';
                }

                modalContent.innerHTML = transcriptHtml;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            modalContent.innerHTML = '<p class="text-red-500">An error occurred while fetching transcripts.</p>';
        });
}