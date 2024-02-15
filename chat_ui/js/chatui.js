// import { createApp, ref } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js'



const { createApp, ref } = Vue
const jobPollIntervalMs = 5000;
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
        };

        let name = localStorage.getItem("name");
        if (!name || name === "null") {
            this.$nextTick(() => {
                // $('#modal').modal('show');
                document.getElementById("showNameModal").click();
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
        setTimeout(this.updateJobs, 500);
    },
    computed: {
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
                    if (newJob.status != this.jobs[newJob.id].status
                        || newJob.updated != this.jobs[newJob.id].updated
                    ) {
                        this.getJobData(newJob);
                    } else {
                        // console.debug("no update for job", newJob.id);
                    }

                }

            })
        },
        getNewWebSocket: function () {
            if (this.ws != null) {
                console.error("Already have a websocket!");
                return;
            }
            let ws = new WebSocket("/ws");
            ws.addEventListener("message", (event) => {
                const response = JSON.parse(event.data);
                // console.debug(response);
                switch (response.message) {
                    case "jobs":
                        this.fromWebSocketJobs(response);
                        break;
                    case "delete":
                        console.debug("Removing job", response.payload);
                        delete this.jobs[response.payload.id];
                        break;
                    case "error":
                        console.error("Error from server", response.payload);
                        // TODO: show a message in the UI
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
            // console.debug(this.ws);
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
                    console.debug("prompt sent");
                    this.currentPrompt = "";
                    setTimeout(this.updateJobs, 500);
                }
            });
        },
        getJobData: function (job) {
            console.debug("getJobData", job);
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
                console.debug("getJobData Response", responseData);
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
            // // post to /user with payload in json format
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
                    // document.getElementById('closeModal').click()
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
