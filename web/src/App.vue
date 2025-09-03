<script setup>

</script>

<template>
    <div class="container">
        <div class="viewfinder">
            <img src="http://dvrpi.local:8000/stream" />
        </div>
        <div class="controls">

        </div>
    </div>
</template>

<script>
export default {
    props: {

    },
    data() {
        return {

        };
    },
    methods: {

    },
}
</script>

<style lang='scss' scoped>
.container{
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    width: 100%;
    height: 100%;

    .viewfinder{
        // width: 100%;
        width: fit-content;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: black;
        flex-shrink: 0;
        max-width: 80%;

        img{
            width: 100%;
            
        }
    }
}
</style>