import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() => runApp(MyApp());

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(home: HomePage());
  }
}

class HomePage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Live Transcript")),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => LiveTranscriptPage()),
                );
              },
              icon: Icon(Icons.mic),
              label: Text("Microphone Local", style: TextStyle(fontSize: 18)),
            ),
            SizedBox(height: 32),
            ElevatedButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => LiveStreamPage()),
                );
              },
              icon: Icon(Icons.live_tv),
              label: Text("Live Stream"),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.deepPurple,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class LiveTranscriptPage extends StatefulWidget {
  @override
  _LiveTranscriptPageState createState() => _LiveTranscriptPageState();
}

class _LiveTranscriptPageState extends State<LiveTranscriptPage> {
  String transcript = "";
  Timer? timer;
  bool isRecording = false;

  final String server = "http://127.0.0.1:5000"; // ⚠️ change si téléphone

  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(Duration(seconds: 1), (_) => fetchTranscript());
  }

  Future<void> fetchTranscript() async {
    final response = await http.get(Uri.parse("$server/live_transcript"));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      setState(() {
        transcript = data["text"];
      });
    }
  }

  Future<void> startRecording() async {
    await http.get(Uri.parse("$server/start"));
    setState(() => isRecording = true);
  }

  Future<void> stopRecording() async {
    await http.get(Uri.parse("$server/stop"));
    setState(() => isRecording = false);
  }

  Future<void> resetTranscript() async {
    await http.get(Uri.parse("$server/reset"));
    setState(() {
      transcript = "";
      isRecording = false;
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Micro Live")),
      body: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              ElevatedButton(
                onPressed: isRecording ? null : startRecording,
                child: Text("Démarrer"),
              ),
              ElevatedButton(
                onPressed: isRecording ? stopRecording : null,
                child: Text("Stop"),
              ),
              ElevatedButton(onPressed: resetTranscript, child: Text("Reset")),
            ],
          ),
          Expanded(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: SingleChildScrollView(
                child: Text(transcript, style: TextStyle(fontSize: 20)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class LiveStreamPage extends StatefulWidget {
  @override
  _LiveStreamPageState createState() => _LiveStreamPageState();
}

class _LiveStreamPageState extends State<LiveStreamPage> {
  final urlController = TextEditingController();
  String transcript = "";
  Timer? timer;
  bool isTranscribing = false;

  final String server = "http://127.0.0.1:5000"; // ⚠️ change si téléphone

  Future<void> fetchStreamTranscript() async {
    final response = await http.get(Uri.parse("$server/stream_transcript"));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      setState(() => transcript = data["text"] ?? "");
    }
  }

  Future<void> startStream() async {
    if (urlController.text.isEmpty) return;

    await http.get(
      Uri.parse(
        "$server/start_stream?url=${Uri.encodeComponent(urlController.text)}",
      ),
    );

    setState(() {
      isTranscribing = true;
      transcript = "";
    });

    timer = Timer.periodic(
      Duration(seconds: 2),
      (_) => fetchStreamTranscript(),
    );
  }

  Future<void> stopStream() async {
    await http.get(Uri.parse("$server/stop_stream"));
    timer?.cancel();
    setState(() => isTranscribing = false);
  }

  @override
  void dispose() {
    timer?.cancel();
    urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Live Stream")),
      body: Column(
        children: [
          Padding(
            padding: EdgeInsets.all(16),
            child: TextField(
              controller: urlController,
              decoration: InputDecoration(
                hintText: "URL YouTube Live / Twitch",
                border: OutlineInputBorder(),
              ),
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              ElevatedButton(
                onPressed: isTranscribing ? null : startStream,
                child: Text("Démarrer"),
              ),
              ElevatedButton(
                onPressed: isTranscribing ? stopStream : null,
                child: Text("Stop"),
              ),
            ],
          ),
          Expanded(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: SingleChildScrollView(
                child: Text(transcript, style: TextStyle(fontSize: 18)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
