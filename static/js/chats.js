function send() {
    let msg = document.getElementById("msg").value;
    if (!msg) return;

    let chat = document.getElementById("chatbox");
    chat.innerHTML += "<p><b>You:</b> " + msg + "</p>";

    fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg })
    })
    .then(res => res.json())
    .then(data => {
        chat.innerHTML += "<p><b>Bot:</b> " + data.reply + "</p>";
        chat.scrollTop = chat.scrollHeight;
    });

    document.getElementById("msg").value = "";
}
