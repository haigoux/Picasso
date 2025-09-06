<script setup>

</script>

<template>
    <div class="passcode-entry" v-if="authorized === false">
        <label for="passcode">Enter Passcode:</label>
        <input type="password" id="passcode" v-model="_passcode_input" />
        <button @click="enterPasscode(_passcode_input)">Submit</button>
    </div>
    <div class="container" v-if="authorized === true">
        <div class="controls">
            <!-- <div class="row">
                <span class="status">
                    STATUS: <span>status</span>
                </span>
            </div> -->
            <div class="row">
                <button @click="startRecording" v-if="!metadata.recording">
                    <img src="@/assets/record.png" />
                </button>
                <button v-else @click="stopRecording">
                    <img src="@/assets/stop.png" />
                </button>
                <button @click="takePicture">
                    <img class="small invert" src="@/assets/camera.png" />
                </button>
            </div>
            <!-- <div class="row">
                <button>
                    <img class="small" src="@/assets/save.png" />
                </button>
                <button>
                    <img class="small" src="@/assets/folder.png" />
                </button>
            </div> -->
            <div class="route">
                <RouterView />
            </div>
        </div>
        <div class="viewfinder">
            <div class="overlay" v-if="metadata">
                <div class="top">
                    <div class="recording-tag" v-if="metadata.recording">
                        <img src="@/assets/record_dot.png" />
                        <span>
                            RECORDING
                        </span>
                        <span>{{ recording_length_str }}</span>
                    </div>
                    <div class="recording-tag" v-if="picture_taken">
                        <img class="invert" src="@/assets/camera.png" />
                        <span>
                            PICTURE SAVED
                        </span>
                        <span>{{ (pic_size_bytes / 1024).toFixed(1) }} KB</span>
                    </div>
                    <div class="recording-tag" v-if="!metadata.saving.complete">
                        <img src="@/assets/floppy.png" />
                        <span>
                            SAVING
                        </span>
                        <span>{{ (metadata.saving.total_bytes / (1024 * 1024)).toFixed(1) }} MB</span>
                    </div>
                </div>
                <!-- <div class="center-right">
                    <div class="audio-meter">
                        <div class="fill" style="height: 100%;"></div>
                    </div>
                    <div class="audio-meter">
                        <div class="fill" style="height: 100%;"></div>
                    </div>
                </div> -->
                <div class="bottom" v-if="metadata.storage_usage">
                    <div class="stat">
                        <span>
                            MEMORY
                        </span>
                        <div class="progress">
                            <div class="fill" :style="{ width: memory_used_percent + '%' }"></div>
                        </div>
                        <span>
                            {{ memory_used_percent.toFixed(1) }}%
                        </span>
                    </div>
                    <div class="stat">
                        <span>
                            STORAGE ({{ metadata.root }})
                        </span>
                        <div class="progress">
                            <div class="fill" :style="{ width: storage_used_percent + '%' }"></div>
                        </div>
                        <span>
                            {{ storage_used_percent.toFixed(1) }}% of {{ (metadata.storage_usage.total_bytes / (1024 *
                            1024 * 1024)).toFixed(0) }} GB
                        </span>
                    </div>
                </div>
            </div>
            <img v-if="stream_src" :src="stream_src" alt="Camera Stream" />
            <div class="loading" v-else>Preview Loading...</div>
        </div>
    </div>
</template>

<script>
export default {
    props: {

    },
    data() {
        return {
            stream_src: null,
            metadata: {
                saving: {
                    complete: true,
                    total_bytes: 0,
                    moved_bytes: 0,
                }
            },
            recording_length_str: '--:--:--',
            pic_size_bytes: 0,
            picture_taken: false,
            storage_used_percent: 0,
            memory_used_percent: 0,
            authorized: null,
            _passcode_input: '',
            _header_x_picasso_passcode: '', // passcode for secure endpoints
        };
    },
    methods: {
        enterPasscode(code){
            // save to cookie
            this.$cookie.set('picasso_passcode', code, { expires: 7 });
            this._header_x_picasso_passcode = code;
            // reload
            this.getStreamUrl();
            this.getMetadata();
        },
        get(url, callback) {
            fetch(url, {
                headers: {
                    'X-Picasso-Passcode': this._header_x_picasso_passcode
                }
            })
                .then(response => {
                    if (response.status === 401) {
                        this.authorized = false;
                        throw new Error('Unauthorized');
                    }else if (response.status === 200) {
                        this.authorized = true;
                        this.getStreamUrl();
                    }
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    callback(data);
                })
                .catch(error => {
                });
        },
        getStreamUrl() {
            // get the ip address of the server running this website
            const ip = window.location.hostname;
            this.stream_src = `http://${ip}:8000/stream`;
            if (this._header_x_picasso_passcode) {
                this.stream_src += `?passcode=${this._header_x_picasso_passcode}`;
            }
        },
        getDurationString() {
            if (!this.metadata.recording) {
                this.recording_length_str = '--:--:--';
                return;
            }
            // the time formatted expected is iso timestamp
            const start_time = this.metadata.start_time;
            // convert the timestamp to HH:MM:SS relative to now
            const now = new Date();
            const seconds = Math.floor((now - new Date(start_time)) / 1000);
            this.recording_length_str = new Date(seconds * 1000).toISOString().substr(11, 8);
        },
        startRecording() {
            this.get(`http://${window.location.hostname}:8000/start_recording`, (data) => {
            });
        },
        stopRecording() {
            this.get(`http://${window.location.hostname}:8000/stop_recording`, (data) => {
            });
        },
        takePicture() {
            this.get(`http://${window.location.hostname}:8000/take_picture`, (data) => {
                this.picture_taken = true;
                let size_bytes = 0;
                if (data.size_bytes) {
                    size_bytes = data.size_bytes;
                }
                this.pic_size_bytes = size_bytes;
                setTimeout(() => {
                    this.picture_taken = false;
                }, 2000);
            });
        },
        getMetadata() {
            this.get(`http://${window.location.hostname}:8000/metadata`, (data) => {
                this.metadata = data.metadata;
                
                if (this.metadata.storage_usage) {
                    this.storage_used_percent = (this.metadata.storage_usage.used_bytes / this.metadata.storage_usage.total_bytes) * 100;
                }
                if (this.metadata.memory_usage) {
                    this.memory_used_percent = (this.metadata.memory_usage.used_bytes / this.metadata.memory_usage.total_bytes) * 100;
                }
                if (this.metadata.last_picture) {
                    this.pic_size_bytes = this.metadata.last_picture.size_bytes;
                    this.picture_taken = true;
                    setTimeout(() => {
                        this.picture_taken = false;
                    }, 3000);
                }
            });
        },
    },
    mounted() {
        // load passcode from cookie
        const savedPasscode = this.$cookie.get('picasso_passcode');
        if (savedPasscode) {
            this._header_x_picasso_passcode = savedPasscode;
        }
            this.getMetadata();

        setInterval(() => {
            this.getDurationString();
        }, 1000);
        setInterval(() => {
            this.getMetadata();
        }, 500);
    }
}
</script>

<style lang='scss' scoped>
.passcode-entry {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    top: 0;
    bottom: 0;
    width: 100%;
    z-index: 10;
    position: absolute;
    gap: 8px;
    background-color: rgba(22, 22, 22, 0.568);
    backdrop-filter: blur(5px);


    label {
        font-size: 1rem;
        font-family: monospace;
        color: white;
    }

    input {
        padding: 8px;
        font-size: 1rem;
        border-radius: 4px;
        border: 1px solid #ccc;
        font-family: monospace;
    }

    button {
        padding: 8px 16px;
        font-size: 1rem;
        border-radius: 4px;
        border: none;
        background-color: rgba(91, 255, 233, 0.692);
        cursor: pointer;
        font-family: monospace;

        &:hover {
            background-color: rgba(91, 255, 233, 0.8);
        }
    }
}

.container {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    height: 100%;

    .controls {
        display: flex;
        align-items: flex-start;
        justify-content: flex-start;
        flex-direction: column;
        flex-shrink: 0;
        width: 100%;
        height: 100%;
        max-width: 40%;
        padding-top: 16px;

        .row {
            width: 100%;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-around;
            gap: 16px;
            padding: 0 16px;
            margin-bottom: 10px;

            .status {
                font-weight: bolder;
                text-align: left;
                width: 100%;
                color: white;
                font-size: 1rem;
                font-family: monospace;

                span {
                    font-weight: normal;
                }
            }
        }

        button {
            background: none;
            border: none;
            width: 50%;
            ;
            height: 80px;
            cursor: pointer;
            background-color: rgba(243, 243, 243, 0.1);
            display: flex;
            align-items: center;
            border-radius: 5px;
            justify-content: center;

            img {
                width: 100px;
                height: 100px;

                &.small {
                    width: 50px;
                    height: 50px;
                }

                &.invert {
                    filter: invert(100%);
                }
            }

            &:active {
                background-color: rgba(91, 255, 233, 0.692);

                img {
                    user-select: none;
                }
            }
        }
    }

    .viewfinder {
        // width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: black;
        flex-shrink: 0;
        width: 100%;
        max-width: 60%;
        position: relative;

        .loading {
            color: white;
            font-size: 1.5rem;
            width: 100%;
            text-align: center;
            font-family: monospace;
        }

        img {
            width: 100%;

        }

        .overlay {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            pointer-events: none;

            * {
                text-shadow: 1px 1px 0px black;
            }

            .top,
            .bottom {
                width: 100%;
                text-align: center;
                color: white;
                font-size: 1.2rem;
                padding: 8px 0;
                font-family: monospace;
                display: flex;
                flex-direction: row;
                justify-content: space-between;
                padding: 16px;
                font-family: "vcr";
                gap: 8px;

                .recording-tag {
                    display: flex;
                    flex-direction: column;
                    align-items: flex-start;
                    justify-content: flex-start;
                    gap: 8px;
                    position: relative;
                    margin-left: 26px;

                    img {
                        width: 16px;
                        height: 16px;
                        animation: blinking 1s infinite;
                        position: absolute;
                        top: 2px;
                        left: -23px;

                        &.large {
                            width: 32px;
                            height: 32px;
                            left: -37px;
                            top: -5px;
                        }

                        &.invert {
                            filter: invert(100%);
                        }
                    }
                }
            }

            .center-right {
                position: absolute;
                top: 50%;
                transform: translateY(-50%);
                right: 0;
                bottom: 0;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 2px;
                padding: 16px;
                height: 50%;

                .audio-meter {
                    width: 20px;
                    height: 100%;
                    background-color: rgba(0, 0, 0, 0.2);
                    overflow: hidden;
                    border: 2px inset rgba(255, 255, 255, 0.884);

                    .fill {
                        width: 100%;
                        background-color: rgb(255, 44, 44);
                    }
                }
            }

            .bottom {
                justify-content: flex-start;

                .stat {
                    display: flex;
                    flex-direction: column;
                    align-items: flex-start;
                    justify-content: flex-start;
                    gap: 8px;
                    font-size: 0.8rem;

                    .progress {
                        width: 100px;
                        height: 12px;
                        background-color: rgba(255, 255, 255, 0.2);
                        overflow: hidden;
                        border: 2px inset rgba(255, 255, 255, 0.884);

                        .fill {
                            height: 100%;
                            background-color: rgb(255, 255, 255);
                        }
                    }
                }
            }


        }
    }

    @media (max-width: 500px) {
        flex-direction: column-reverse;
        align-items: flex-start;
        justify-content: flex-start;
        height: fit-content;

        .controls {
            flex-direction: column;
            max-width: 100%;
            width: 100%;
            height: auto;
            align-items: center;
            justify-content: center;
            gap: 8px;

            .row {
                flex-direction: row;
                gap: 8px;
                margin-bottom: 0;
                width: 100%;
                align-items: center;
            }

            button {
                width: 100%;
                margin: 0;

                img {
                    width: 60px;
                    height: 60px;

                    &.small {
                        width: 30px;
                        height: 30px;
                    }
                }
            }
        }

        .viewfinder {
            max-width: none;
            width: 100%;
            flex-shrink: 0;
            height: unset;

            img {
                width: 100%;

            }
        }
    }
}

@keyframes blinking {
    0% {
        opacity: 1;
    }

    50% {
        opacity: 0;
    }

    100% {
        opacity: 1;
    }
}
</style>