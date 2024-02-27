const { createApp, ref } = Vue
const jobPollIntervalMs = 2500;
const defaultNextRunMs = 250;

createApp({
    data() {
        var data = {
            name: "",
            userModalHidden: false,
            userModalErrors: "",
            userModalSuccess: "",
            jobs: {},
            userid: "",
            useCase: "plain",
            currentPrompt: "",
            poller: null,
            ws: null,
            waitingJobs: null,
            waitingPoller: null,
            initialLoad: true,
        };

        let name = localStorage.getItem("name");
        if (!name || name === "null") {
            this.$nextTick(() => {
                const show_name_modal = document.getElementById("showNameModal");
                if (show_name_modal) {
                    show_name_modal.click();
                } else {
                    console.debug("Couldn't find showNameModal button!");
                }
            });
        } else {
            data.name = name;
        }

        let userid = localStorage.getItem('userid');
        if (!userid) {
            userid = crypto.randomUUID();
            if (!userid) {
                console.error("Couldn't generate a UUID!");
            }
            localStorage.setItem('userid', userid);
        }

        data.userid = userid;
        return data;
    },
    setup() {
    },
    created() {
        this.getNewWebSocket();
        this.poller = setInterval(this.updateJobs, jobPollIntervalMs);
        this.waitingPoller = setInterval(this.updateWaiting, defaultNextRunMs);
        setTimeout(this.updateJobs, defaultNextRunMs);
    },
    computed: {
        haveWaitingJobs() {
            return this.waitingJobs !== null && this.waitingJobs > 0;
        },
        hasUserModalErrors() {
            return this.userModalErrors.length > 0;
        },
        hasUserModalSuccess() {
            return this.userModalSuccess.length > 0;
        },
        needsName() {
            return !this.userModalHidden;
        },
        hasTasks() {
            return this.tasks.length > 0;
        },

        noJobs() {
            return Object.keys(this.jobs).length === 0;
        },
        getJobList() {
            let jobs = Object.keys(this.jobs).map((jobid) => {
                let val = this.jobs[jobid];
                val.id = jobid;
                return val
            });
            jobs.sort((left, right) => {
                let left_time = new Date(left.created);
                if (left.updated) {
                    left_time = new Date(left.updated);
                }
                let right_time = new Date(right.created);
                if (right.updated) {
                    right_time = new Date(right.updated);
                }
                return right_time - left_time;
            });
            return jobs
        },
        isPolling() {
            return !(this.ws === null || this.ws.readystate == 0)
        }
    },
    methods: {
        updateWaiting: function () {
            const payload = { "userid": this.userid, "message": "waiting" };
            this.checkForWebSocket();
            this.ws.send(JSON.stringify(payload));
        },
        checkForWebSocket: function () {
            if (!this.isPolling) {
                this.getNewWebSocket();
            }
        },
        deleteJob: function (jobid) {
            this.checkForWebSocket();

            const payload = {
                "message": "delete",
                "userid": this.userid,
                "payload": jobid,
            }
            this.ws.send(JSON.stringify(payload));
            delete this.jobs[jobid];
        },
        // handle the "jobs" response from the websocket
        fromWebSocketJobs: function (response) {
            response.payload.forEach((newJob) => {
                if (!(newJob.id in this.jobs)) {
                    this.jobs[newJob.id] = newJob;
                    this.getJobData(newJob);
                } else {
                    const existingJob = this.jobs[newJob.id];

                    // because we parse it going into the internal state, and comparing date objects is weird. thanks JavaScript.
                    const newDate = new Date(newJob.updated).toLocaleString();
                    const existingDate = new Date(existingJob.updated).toLocaleString();

                    if (newJob.status != existingJob.status
                    ) {
                        console.debug(`Updating job id=${newJob.id} because status ${existingJob.status} != ${newJob.status}`);
                        this.getJobData(newJob);
                    }
                    else if (newDate !== existingDate
                    ) {
                        console.debug(`Updating job id=${newJob.id} because 'updated' ${existingDate} != ${newDate}`);
                        this.getJobData(newJob);
                    }
                }

            })
        },
        getNewWebSocket: function () {
            if (this.ws !== null) {
                console.error("Already have a websocket!");
                return;
            }
            // build a websocket URI
            var loc = window.location, websocket_uri;
            if (loc.protocol === "https:") {
                websocket_uri = "wss:";
            } else {
                websocket_uri = "ws:";
            }
            websocket_uri += "//" + loc.host;
            websocket_uri += "/ws";


            let ws = new WebSocket(websocket_uri);
            ws.addEventListener("message", (event) => {
                const response = JSON.parse(event.data);
                switch (response.message) {
                    case "jobs":
                        this.fromWebSocketJobs(response);
                        this.initialLoad = false;
                        break;
                    case "delete":
                        console.debug("Removing job", response.payload);
                        delete this.jobs[response.payload.id];
                        break;
                    case "error":
                        console.error("Error response from server", response.payload);
                        break;
                    case "resubmit":
                        setTimeout(this.updateJobs, defaultNextRunMs);
                        break;
                    case "waiting":
                        this.waitingJobs = response.payload;
                        break;
                    default:
                        console.error("Unknown message", response.message);
                }


            });

            ws.addEventListener("error", (event) => {
                console.log("Websocket connection failed ", event.data);
                this.ws = null;
            });
            ws.addEventListener("close", (event) => {
                console.log("Websocket connection closed", event.data);
                this.ws = null;
            });
            this.ws = ws;
        },
        startPoller: function () {
            this.stopPoller();
            this.poller = setInterval(this.updateJobs, jobPollIntervalMs);
            console.debug("Started polling again...");
        },
        stopPoller: function () {
            clearInterval(this.poller);
            console.debug("Stopped poller");
            this.ws = null;
        },
        updateJobs: function () {
            const payload = { "userid": this.userid, "message": "jobs" };
            this.checkForWebSocket();
            this.ws.send(JSON.stringify(payload));
        },
        sendPrompt: function () {
            const payload = {
                "userid": this.userid,
                "prompt": this.currentPrompt,
                "request_type": this.useCase,
            }
            if (!this.currentPrompt.trim()) {
                console.error("Prompt is empty");
                return;
            }
            fetch('/job', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            }).catch(err => {
                console.error(`failed to send prompt: ${err}`);
            }).then(response => {
                if (response.ok) {
                    console.debug("Prompt sent!");
                    this.currentPrompt = "";
                    setTimeout(this.updateJobs, defaultNextRunMs);
                }
            });
        },
        resubmitJob: function (jobid) {
            console.debug("Resubmitting job", jobid);
            const payload = { "userid": this.userid, "message": "resubmit", "payload": jobid };
            this.checkForWebSocket();
            this.ws.send(JSON.stringify(payload));
        },
        getJobData: function (job) {
            fetch(`/jobs/${this.userid}/${job.id}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            }).then(response => {
                if (response.ok) {
                    return response.json();
                }
                throw new Error('Failed to fetch job data');
            }).then(responseData => {
                if (!(responseData.id in this.jobs)) {
                    if (responseData.status != "hidden") {
                        this.jobs[responseData.id] = responseData;
                    }
                } else {
                    if (responseData.status == "hidden") {
                        delete this.jobs[responseData.id];
                    } else {
                        // update the existing job
                        Object.keys(responseData).forEach((key) => {
                            this.jobs[responseData.id][key] = responseData[key];
                        });

                    }
                }

            }).catch(err => {
                console.error(`failed to fetch job data: ${err}`);
            });
        },
        saveUserDetails: function () {

            const payload = {
                "name": this.name,
                "userid": this.userid
            };
            // post to /user with payload in json format
            fetch('/user', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            }).catch(err => {
                console.error(`failed to save user details: ${err}`);
                this.userModalErrors = "Failed to save user details! Please try again.";
            }).then(response => {
                if (response.ok) {
                    this.userModalSuccess = "User details saved!";
                    localStorage.setItem("name", this.name);
                }
                // hide the bootstrap modal
            });

        },
        colorFromStatus: function (status) {
            switch (status) {
                case "created":
                    return "text-muted"
                case "running":
                    return "text-primary";
                case "complete":
                    return "text-success";
                case "error":
                    return "text-danger";
                default:
                    return "text-muted";
            }
        }
    },
    watch: {
        name: function (newName, oldName) {
            if (newName) {
                this.saveUserDetails();
            }
        }
    }
}).mount('#app')
