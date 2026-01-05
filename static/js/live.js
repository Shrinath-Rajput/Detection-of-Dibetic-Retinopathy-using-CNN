async function fetchData() {
    const res = await fetch("/live_sensor");
    const data = await res.json();

    document.getElementById("hr").innerText =
        data.heart_rate ? data.heart_rate + " BPM" : "-- BPM";

    document.getElementById("spo2").innerText =
        data.spo2 ? data.spo2 + " %" : "-- %";

    document.getElementById("status").innerText = data.status;

    document.getElementById("hr_status").innerText = data.hr_status;
    document.getElementById("spo2_status").innerText = data.spo2_status;
    document.getElementById("risk").innerText = data.risk;
    document.getElementById("advice").innerText = data.advice;
}

setInterval(fetchData, 2000);
fetchData();
