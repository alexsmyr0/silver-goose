// transcribe.swift - listen to a clip and say WHICH words were said and WHEN, to the millisecond.
//
// Same pattern as render_hook.swift, read_cover.swift and to_sdr.swift: where ffmpeg cannot,
// macOS can. Speech recognition runs entirely on this Mac through Apple's SpeechAnalyzer -
// nothing is uploaded. First setup downloads a missing Apple language model; recognition
// then works offline. Models are system-managed and may need downloading again if removed.
//
//   .transcribe audio.wav [--locale en-GB] [--context words.txt] [--alternatives]
//
// Prints JSON on stdout:
//   {"ok":true,"locale":"en-GB","duration":8.77,
//    "words":[{"text":"alright","start":0.32,"end":0.52,"confidence":0.98}, ...]}
//
// Input must be a plain audio file AVAudioFile can open (wav/m4a/caf). The Python side
// extracts one with ffmpeg first - keeping the container handling out here means this file
// only ever does the thing only macOS can do.
import Foundation
import AVFoundation
import Speech

struct Word: Codable {
    let text: String
    let start: Double
    let end: Double
    let confidence: Double?
    /// What the recogniser said before the start was moved onto the voice. Kept so the
    /// correction is visible and checkable rather than something the tool did quietly.
    var rawStart: Double? = nil
}

struct Output: Codable {
    let ok: Bool
    let locale: String?
    let duration: Double?
    let words: [Word]?
    let text: String?
    let alternatives: [String]?
    let error: String?
}

func emit(_ o: Output) -> Never {
    let enc = JSONEncoder()
    enc.outputFormatting = [.withoutEscapingSlashes]
    if let d = try? enc.encode(o), let s = String(data: d, encoding: .utf8) { print(s) }
    exit(o.ok ? 0 : 1)
}

func fail(_ msg: String) -> Never {
    emit(Output(ok: false, locale: nil, duration: nil, words: nil, text: nil,
                alternatives: nil, error: msg))
}

@available(macOS 26.0, *)
func pickLocale(_ want: String) async -> Locale? {
    let installed = await SpeechTranscriber.installedLocales
    // Exact BCP-47 first, then the same language in any region, so "en" finds en-GB rather
    // than failing. Falling back silently to a different LANGUAGE would be worse than failing.
    if let hit = installed.first(where: { $0.identifier(.bcp47).lowercased() == want.lowercased() }) {
        return hit
    }
    let lang = want.split(separator: "-").first.map(String.init)?.lowercased() ?? want.lowercased()
    return installed.first(where: { ($0.language.languageCode?.identifier ?? "").lowercased() == lang })
}

@available(macOS 26.0, *)
func prepareLocale(_ want: String) async -> Locale {
    if let installed = await pickLocale(want) { return installed }
    guard SpeechTranscriber.isAvailable else {
        fail("Apple on-device speech is not available on this Mac.")
    }
    guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: want)) else {
        fail("Apple speech does not support locale \(want) on this Mac.")
    }
    let module = SpeechTranscriber(locale: locale, preset: .transcription)
    do {
        if let download = try await AssetInventory.assetInstallationRequest(supporting: [module]) {
            FileHandle.standardError.write(Data("Downloading Apple's speech model…\n".utf8))
            try await download.downloadAndInstall()
        }
    } catch {
        fail("Could not prepare Apple speech. Connect to the internet and run the launcher again: \(error.localizedDescription)")
    }
    return locale
}

@available(macOS 26.0, *)
func run(path: String, localeWanted: String, context: [String], wantAlternatives: Bool,
         refineOnsets: Bool) async {
    let url = URL(fileURLWithPath: path)
    guard FileManager.default.fileExists(atPath: path) else { fail("no such file: \(path)") }

    let locale = await prepareLocale(localeWanted)

    // audioTimeRange is the whole point - it is what turns a transcript into timings.
    // transcriptionConfidence rides along free and is what lets the panel show which words
    // are worth checking rather than presenting every word as equally certain.
    var attrs: Set<SpeechTranscriber.ResultAttributeOption> = [.audioTimeRange, .transcriptionConfidence]
    var reporting: Set<SpeechTranscriber.ReportingOption> = []
    if wantAlternatives { reporting.insert(.alternativeTranscriptions) }
    _ = attrs

    let transcriber = SpeechTranscriber(locale: locale,
                                        transcriptionOptions: [],
                                        reportingOptions: reporting,
                                        attributeOptions: attrs)

    let analyzer = SpeechAnalyzer(modules: [transcriber])

    // Brand names are where every speech engine falls over, and this project is full of them -
    // Claude, OpenArt, MCP, Zillow. Priming the recogniser with them is the single cheapest
    // accuracy win available, so the caller can pass a word list.
    if !context.isEmpty {
        let ctx = AnalysisContext()
        ctx.contextualStrings = [.general: context]
        try? await analyzer.setContext(ctx)
    }

    let file: AVAudioFile
    do { file = try AVAudioFile(forReading: url) }
    catch { fail("could not read the audio: \(error.localizedDescription)") }
    let duration = Double(file.length) / file.fileFormat.sampleRate

    var words: [Word] = []
    var full = ""
    var alts: [String] = []

    let collector = Task {
        for try await result in transcriber.results {
            let attributed = result.text
            full += String(attributed.characters)
            if wantAlternatives {
                for a in result.alternatives { alts.append(String(a.characters)) }
            }
            // Each RUN carries its own time range. A run is usually a word, but the engine is
            // free to group - so runs are split on whitespace and the range shared out rather
            // than assuming one run is one word.
            for r in attributed.runs {
                guard let range = r.audioTimeRange else { continue }
                let piece = String(attributed[r.range].characters)
                let t0 = range.start.seconds
                let t1 = (range.start + range.duration).seconds
                let conf = r.transcriptionConfidence.map { Double($0) }
                let parts = piece.split(whereSeparator: { $0.isWhitespace })
                if parts.isEmpty { continue }
                if parts.count == 1 {
                    words.append(Word(text: String(parts[0]), start: t0, end: t1, confidence: conf))
                } else {
                    // Share the run's span out by character count. Better than dropping the
                    // extra words, and flagged by being an even split if anyone checks.
                    let total = parts.reduce(0) { $0 + $1.count }
                    var cur = t0
                    for p in parts {
                        let span = (t1 - t0) * Double(p.count) / Double(max(total, 1))
                        words.append(Word(text: String(p), start: cur, end: cur + span, confidence: conf))
                        cur += span
                    }
                }
            }
        }
    }

    do {
        _ = try await analyzer.analyzeSequence(from: file)
        try await analyzer.finalizeAndFinishThroughEndOfInput()
        _ = try await collector.value
    } catch {
        fail("recognition failed: \(error.localizedDescription)")
    }

    words.sort { $0.start < $1.start }

    if refineOnsets, let env = buildEnvelope(url) {
        words = refine(words, with: env)
    }

    emit(Output(ok: true, locale: locale.identifier(.bcp47), duration: duration,
                words: words, text: full.trimmingCharacters(in: .whitespacesAndNewlines),
                alternatives: wantAlternatives ? alts : nil, error: nil))
}

// ---- where he ACTUALLY starts speaking ----
//
// Apple's SpeechAnalyzer hands back a CONTIGUOUS partition of the audio: measured on Steven's
// own clips, 97-98% of word boundaries are exactly the previous word's end. So a word after a
// pause is stamped at the START of the pause rather than at the moment he says it, and on his
// clean camera audio a QUARTER of all words begin in silence that way - off by up to a second.
//
// That is wrong in both directions the tool cares about: a caption would appear before the word
// is spoken, and a cutaway placed on a phrase would land early. The audio itself says where the
// voice really starts, so it is measured and the start moved forward.
//
// Only the START is moved, and only forward, and never past the word's own end. Moving ends
// about as well was tried and made things worse: a word's tail genuinely does fade into the
// room, so its "end in silence" is not an error.

struct Envelope {
    let db: [Float]
    let hop: Double
    let threshold: Float

    func isSpeech(at t: Double) -> Bool {
        let k = Int(t / hop)
        guard k >= 0 && k < db.count else { return false }
        return db[k] > threshold
    }

    /// First moment at or after `t`, within `limit` seconds, where the voice is up.
    func nextSpeech(from t: Double, within limit: Double) -> Double? {
        var k = max(0, Int(t / hop))
        let stop = min(db.count, Int((t + limit) / hop) + 1)
        while k < stop {
            if db[k] > threshold { return Double(k) * hop }
            k += 1
        }
        return nil
    }
}

func buildEnvelope(_ url: URL, hopMS: Double = 5.0, winMS: Double = 20.0,
                   marginDB: Float = 8.0) -> Envelope? {
    guard let file = try? AVAudioFile(forReading: url,
                                      commonFormat: .pcmFormatFloat32,
                                      interleaved: false) else { return nil }
    let fmt = file.processingFormat
    let frames = AVAudioFrameCount(file.length)
    guard frames > 0, let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: frames),
          (try? file.read(into: buf)) != nil, let ch = buf.floatChannelData else { return nil }

    let n = Int(buf.frameLength)
    let rate = fmt.sampleRate
    // Mono already, but average any channels rather than trusting channel 0.
    let chCount = Int(fmt.channelCount)
    var sq = [Double](repeating: 0, count: n)
    for i in 0..<n {
        var acc: Double = 0
        for c in 0..<chCount { let v = Double(ch[c][i]); acc += v * v }
        sq[i] = acc / Double(chCount)
    }
    // Prefix sums so a sliding window is O(1) per hop rather than O(window).
    var pre = [Double](repeating: 0, count: n + 1)
    for i in 0..<n { pre[i+1] = pre[i] + sq[i] }

    let hop = max(1, Int(rate * hopMS / 1000.0))
    let win = max(hop, Int(rate * winMS / 1000.0))
    var db: [Float] = []
    db.reserveCapacity(n / hop + 1)
    var start = 0
    while start < n {
        let a = max(0, start - win/2), b = min(n, start + win/2)
        let mean = (pre[b] - pre[a]) / Double(max(1, b - a))
        db.append(Float(10.0 * log10(mean + 1e-12)))
        start += hop
    }
    guard !db.isEmpty else { return nil }
    // The quiet tenth of the clip is the room, not the voice. A fixed dB threshold would be
    // wrong the moment a clip is recorded somewhere else.
    let floorDB = db.sorted()[Int(Double(db.count) * 0.10)]
    return Envelope(db: db, hop: Double(hop) / rate, threshold: floorDB + marginDB)
}

func refine(_ words: [Word], with env: Envelope) -> [Word] {
    var out: [Word] = []
    out.reserveCapacity(words.count)
    for w in words {
        var s = w.start
        if !env.isSpeech(at: s) {
            // Never move a start past its own end: that would invert the word.
            let room = max(0.0, w.end - w.start)
            if room > 0, let t = env.nextSpeech(from: s, within: room), t < w.end { s = t }
        }
        out.append(Word(text: w.text, start: s, end: w.end, confidence: w.confidence,
                        rawStart: w.start))
    }
    return out
}

// ---- arguments ----
var args = Array(CommandLine.arguments.dropFirst())
var path: String? = nil
var localeWanted = "en-US"
var context: [String] = []
var wantAlternatives = false
var prepareOnly = false
var refineOnsets = true          // on by default: the raw timings are measurably wrong
var i = 0
while i < args.count {
    let a = args[i]
    switch a {
    case "--prepare":
        prepareOnly = true
    case "--locale":
        i += 1; if i < args.count { localeWanted = args[i] }
    case "--context":
        i += 1
        if i < args.count {
            let v = args[i]
            // A file of one phrase per line, or a comma-separated list inline.
            if FileManager.default.fileExists(atPath: v),
               let body = try? String(contentsOfFile: v, encoding: .utf8) {
                context = body.split(whereSeparator: \.isNewline)
                    .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            } else {
                context = v.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                    .filter { !$0.isEmpty }
            }
        }
    case "--alternatives":
        wantAlternatives = true
    case "--raw-times":
        // Escape hatch for the accuracy harness, so the correction can be measured against
        // the thing it corrects rather than taken on trust.
        refineOnsets = false
    default:
        if path == nil { path = a }
    }
    i += 1
}

if #available(macOS 26.0, *) {
    if prepareOnly {
        let locale = await prepareLocale(localeWanted)
        emit(Output(ok: true, locale: locale.identifier(.bcp47), duration: nil, words: nil,
                    text: nil, alternatives: nil, error: nil))
    }
    guard let p = path else { fail("usage: .transcribe audio.wav [--locale en-US], or --prepare") }
    await run(path: p, localeWanted: localeWanted, context: context,
              wantAlternatives: wantAlternatives, refineOnsets: refineOnsets)
} else {
    fail("needs macOS 26 or newer for on-device word timings")
}
