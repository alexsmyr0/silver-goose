// render_hook.swift - draws the hook captions as transparent PNGs.
//
// Why this exists at all: ffmpeg cannot draw our text. The Homebrew build on this Mac has
// no drawtext filter, and even where it exists it renders colour emoji as empty boxes.
// macOS draws emoji natively, so every piece of text and every logo is drawn HERE and
// handed to ffmpeg as a finished picture to lay over the video.
//
// make_videos.py compiles this on first use; you never run it directly.
//
//   .render_hook <spec.json>
//
// The spec says what to draw; this writes line.png / claude.png / plusshorts.png /
// money.png into out_dir. Each is a full 1080x1920 transparent frame, so ffmpeg only ever
// has to overlay them at 0,0 and switch them on and off at the right moment.

import AppKit
import CoreText

// ---- canvas -----------------------------------------------------------------
let W = 1080.0, H = 1920.0

// ---- layout, measured off the reference videos ------------------------------
// The card slots DO NOT MOVE as pieces appear. In the reference, the Claude card sits at
// exactly the same x whether it is alone or sitting next to Shorts - the layout is fixed
// from the start and the pieces just show up in it. Sliding them would look wrong.
let LINE_TOP     = 290.0     // puts the ink at y=298, matching the reference exactly
let LINE_SIZE    = 82.5
let CARD_BOTTOM  = 467.0     // both logo cards are bottom-aligned here
let CARD_HEIGHT  = 202.0
let CARD_GAP     = 60.0      // space either side of the "+"
let PLUS_SIZE    = 88.0
let MONEY_TOP    = 510.0
let MONEY_SIZE   = 83.0

// ---- the two STATIC formats -------------------------------------------------
// Two of the reference account's other formats put their caption up on the FIRST FRAME and
// never move it - no build-up, nothing appearing on the beat:
//
//   "card"     the money card, whole, from frame one. No opening line at all.
//   "compare"  two fixed lines, "<the bad option> X" over "<the good option> tick".
//              No money card at any point.
//
// In both, the block sits HIGHER than ours, because ours has to leave room for the opening
// line above the card and these have no line. These are the measured differences, taken off
// four reference reels at 720x1280 and scaled by 1.5 to this canvas:
//
//   their card bottom  420  vs ours 463  ->  43 higher
//   their money top    483  vs ours 515  ->  32 higher  (this keeps their 63px gap)
//   their text centre  314  vs ours 376  ->  60 higher
//
// If these ever look wrong, measure a reference frame again rather than nudging by eye.
let CARD_RISE       = 43.0
let CARD_MONEY_RISE = 32.0
let COMPARE_RISE    = 60.0
// The content-farm format puts its caption LOWER, not higher - measured off Steven's own
// video, the ink starts at y=389 against y=298 for the others, so it drops 91px. A negative
// rise, because "rise" moves the block up and this one goes down. The size is unchanged: the
// text block measures 642px wide there against 638px here, which is the same font at the same
// size within a rounding error.
let FARM_DROP       = 87.0

// The outline is drawn as its OWN pass underneath the white fill, not as a stroke on the
// filled text. AppKit's negative-strokeWidth trick centres the stroke on the glyph outline,
// so half of it eats INTO the letter - the white goes thin and spindly and the whole thing
// reads as the wrong font. Stroking first and filling on top keeps the letters full weight
// and puts the black entirely outside them, which is what CapCut does.
// ---- word-by-word captions -------------------------------------------------
// Measured across 173 of Steven's CapCut projects and 9,259 caption chunks, not chosen.
//   font   TikTok Display Medium - assets/font.ttf is byte-identical to CapCut's own copy
//          (sha1 db1c0d40...), so there is nothing to install
//   size   CapCut size 10. Point size is 6.25x the CapCut number at 1080x1920, so 62.5pt.
//   fill   pure white, stroke black at 0.06em outward - which is the OUTLINE 12.5 below
//   place  centred, and the stored y is the centre of the EM BOX, not of the ink:
//          baseline = (1 - y) * 960 + 0.288 * pt.  His latest project (0824) has y=-0.5704,
//          giving 1507.5px, so the baseline lands at 1525.5px from the top.
//   none of: shadow, background box, letter spacing, animation. They hard-cut on and off.
let CAP_SIZE     = 62.5
let CAP_BASELINE = 1525.5    // from the top of a 1920 frame
let CAP_MAXW     = 885.6     // his line_max_width, 0.82 of the frame

let OUTLINE      = 12.5      // stroke-only pass, % of font size; half of it shows
let LINE_HEIGHT  = 0.905     // reference line pitch is 79px, not AppKit's 84
// The comparison format is two separate statements rather than one wrapped sentence, and the
// reference does NOT tighten their spacing: measured pitch 93px against the 83px our
// tightened setting gives, which is the difference between 0.905 and plain 1.0.
let COMPARE_LINE_HEIGHT = 1.0

// ---- font -------------------------------------------------------------------
// CapCut calls this one "Classic". It is really TikTok Display Medium, and it lives in
// CapCut's own cache rather than being installed on the system, so we register the file
// directly. make_videos.py copies it into the campaign's assets/ so the tool does not depend
// on CapCut still being installed.
//
// THERE IS NO FALLBACK TO A SYSTEM FONT, AND THAT IS THE POINT OF THIS FUNCTION.
// There was one until 27 Aug 2026 - `NSFont.systemFont(ofSize: size, weight: .heavy)` - and it
// cost five finished pump.fun videos. The spec carried a font path into ANOTHER Mac's home
// folder, the file was not there, AppKit handed back the system font without a word, and this
// renderer, ffmpeg, the ledger and the panel every one of them reported success. Nothing in
// the tool noticed. The only thing that caught it was Steven looking at the picture - after
// the videos were built and one was already posted.
//
// The heavy system font is CLOSE to this one at caption size, which is what let it through:
// side by side it is a little wider and a little rounder, and on its own it just looks like a
// caption. Being nearly right is what makes it dangerous, not what makes it acceptable.
//
// So: a font that cannot be loaded from the file it was told to load stops the build.
// `render_pump.swift` refuses in exactly the same way - if you change one, change the other.
func fontFail(_ why: String, _ file: String) -> Never {
    FileHandle.standardError.write(("The caption font could not be loaded, so nothing was drawn.\n"
        + "  " + why + "\n"
        + "  looked for: " + file + "\n"
        + "  It is TikTok Display Medium, and CapCut is where the tool copies it from.\n"
        + "  Videos are never built in a substitute font - that is deliberate.\n")
        .data(using: .utf8)!)
    exit(1)
}

func loadFont(_ path: String, _ size: Double) -> NSFont {
    let file = (path as NSString).expandingTildeInPath
    guard !file.isEmpty, FileManager.default.fileExists(atPath: file) else {
        fontFail("The font file is not there.", file)
    }
    let url = URL(fileURLWithPath: file)
    CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    // Looked up by the name INSIDE the file, never by a name written here. A hardcoded name
    // matches whatever this Mac happens to have installed under it, which is the same silent
    // substitution arriving through a different door - and this function used to do exactly
    // that, asking for "TikTok Display Medium" no matter which file it had just registered.
    guard let data = CGDataProvider(url: url as CFURL), let cg = CGFont(data),
          let psName = cg.postScriptName else {
        fontFail("The file is there, but macOS could not read a font out of it.", file)
    }
    guard let font = NSFont(name: psName as String, size: size) else {
        fontFail("macOS would not open \(psName) from that file.", file)
    }
    return font
}

// Set once the spec has been read, because it depends on the format.
var linePitch = LINE_HEIGHT

func para(_ font: NSFont) -> NSMutableParagraphStyle {
    let p = NSMutableParagraphStyle()
    p.alignment = .center
    p.lineHeightMultiple = linePitch
    return p
}

// Pass 1: the black outline. A POSITIVE strokeWidth means stroke and no fill.
// No shadow, no blur. CapCut draws a hard-edged outline and nothing else; a soft shadow under
// it reads as muddy against a bright background. What looks like a glow in Steven's own reels
// is Instagram's compression, not something he applied.
func outlineAttrs(_ font: NSFont, width: Double = OUTLINE) -> [NSAttributedString.Key: Any] {
    return [.font: font, .strokeColor: NSColor.black, .strokeWidth: width,
            .paragraphStyle: para(font)]
}

// Pass 2: the white letters, full weight, straight over the top.
func fillAttrs(_ font: NSFont) -> [NSAttributedString.Key: Any] {
    return [.font: font, .foregroundColor: NSColor.white, .paragraphStyle: para(font)]
}

func attrs(_ font: NSFont) -> [NSAttributedString.Key: Any] { fillAttrs(font) }

// ---- one transparent frame --------------------------------------------------
func frame(_ draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W), pixelsHigh: Int(H),
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    // Round the corners of the outline stroke. The default is a MITRE join, which on a sharp
    // corner extends until the two edges meet - on the apex of a "4" or a "$" that is a long
    // black spike sticking out of the top of the character. Rounding the join kills it.
    NSGraphicsContext.current?.cgContext.setLineJoin(.round)
    NSGraphicsContext.current?.cgContext.setLineCap(.round)
    NSGraphicsContext.current?.cgContext.setMiterLimit(1.0)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func save(_ rep: NSBitmapImageRep, _ path: String) {
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}

// AppKit's origin is bottom-left; everything above is measured from the top, so flip here.
func drawText(_ s: String, _ font: NSFont, topY: Double, dx: Double = 0, dy: Double = 0) {
    for style in [outlineAttrs(font), fillAttrs(font)] {
        let a = NSAttributedString(string: s, attributes: style)
        let box = a.boundingRect(with: NSSize(width: W - 80, height: H),
                                 options: [.usesLineFragmentOrigin, .usesFontLeading])
        a.draw(with: NSRect(x: 40 + dx, y: H - topY - dy - box.height,
                            width: W - 80, height: box.height),
               options: [.usesLineFragmentOrigin, .usesFontLeading])
    }
}

// A logo card, scaled to CARD_HEIGHT and bottom-aligned in its slot.
//
// `scale` is how tall THIS picture is drawn as a multiple of the card height, and it exists
// because the `claude` slot stopped always being a card. OpenArt and Shorts are white boxes
// of roughly the same shape, so one height suited both; a cut-out of a child on a transparent
// background is nearly square and has no box around it, so at the same height it reads as much
// smaller than the thing beside it. Steven asked for it bigger, 28 Aug 2026.
//
// IT GROWS UPWARD. `y` here is the BOTTOM of the rect, so the bottom edge does not move: both
// pictures still stand on the same line, and the "+" stays centred on the CARD, not on the
// bigger picture. Which picture gets which number lives in `make_videos.LOGO_LEFT_SIZE` - the
// same one place that says what a logo may be called - and arrives in the spec.
func drawLogo(_ img: NSImage, x: Double, dy: Double = 0, scale: Double = 1.0) -> Double {
    let h = CARD_HEIGHT * scale
    let w = h * (img.size.width / max(img.size.height, 1))
    img.draw(in: NSRect(x: x, y: H - CARD_BOTTOM - dy, width: w, height: h))
    return w
}

func logoWidth(_ img: NSImage, _ scale: Double = 1.0) -> Double {
    CARD_HEIGHT * scale * (img.size.width / max(img.size.height, 1))
}

// Captions are positioned by BASELINE, not by the top of a text box like everything else
// here. That is because the measurement that ties us to his own frames is a baseline rule -
// converting it into a box top would mean guessing at AppKit's leading and would drift with
// the font.
func drawCaption(_ s: String, _ font: NSFont, baselineY: Double, outline: Double = OUTLINE) {
    let w = NSAttributedString(string: s, attributes: fillAttrs(font)).size().width
    let x = (W - w) / 2
    let y = H - baselineY            // AppKit's origin is bottom-left
    for style in [outlineAttrs(font, width: outline), fillAttrs(font)] {
        NSAttributedString(string: s, attributes: style)
            .draw(at: NSPoint(x: x, y: y - font.descender.magnitude))
    }
}

// ---- read the spec ----------------------------------------------------------
guard CommandLine.arguments.count > 1,
      let data = FileManager.default.contents(atPath: CommandLine.arguments[1]),
      let spec = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
    FileHandle.standardError.write("render_hook: could not read the spec file\n".data(using: .utf8)!)
    exit(1)
}
let outDir    = spec["out_dir"]  as? String ?? "."
let lineText  = spec["line"]     as? String ?? ""
// "line" (the original: opening line, then the card assembles), "card" (the whole money card
// from frame one, no line) or "compare" (two fixed lines, no card). Anything unrecognised
// falls back to "line", so an older spec still renders the way it always did.
let format    = spec["format"]   as? String ?? "line"
let isCard    = (format == "card")
let isCompare = (format == "compare")
// Both content-farm variants draw the same caption-only frame. Their assets and history are
// separate, but neither uses logos or a money card.
let isFarm    = (format == "farm" || format == "mcp_farm")
let lineRise  = isCompare ? COMPARE_RISE : (isFarm ? -FARM_DROP : 0.0)
let cardRise  = isCard ? CARD_RISE : 0.0
let moneyRise = isCard ? CARD_MONEY_RISE : 0.0
linePitch = isCompare ? COMPARE_LINE_HEIGHT : LINE_HEIGHT
let moneyText = spec["money"]    as? String ?? ""
let fontPath  = spec["font"]     as? String ?? ""

// ---- caption batch mode -----------------------------------------------------
// One process draws every chunk in the video. Doing it the obvious way - one run of this
// program per chunk - costs 84ms of process start each time, which is 10 seconds for a video
// with 120 chunks and buys nothing: the drawing itself is 2ms. Everything below the spec read
// has already been set up, so the loop is nearly free.
if let chunks = spec["chunks"] as? [[String: Any]], !chunks.isEmpty {
    let capFont = loadFont(fontPath, spec["caption_size"] as? Double ?? CAP_SIZE)
    let baseline = spec["caption_baseline"] as? Double ?? CAP_BASELINE
    let dir = outDir + "/cap"
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    var written: [String] = []
    for (i, c) in chunks.enumerated() {
        let text = (c["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let path = String(format: "%@/c%04d.png", dir, i)
        save(frame { if !text.isEmpty { drawCaption(text, capFont, baselineY: baseline, outline: spec["caption_outline"] as? Double ?? OUTLINE) } }, path)
        written.append(path)
    }
    // Printed so the caller never has to guess the filenames or the count.
    print("ok \(written.count)")
    exit(0)
}

// A few pixels of drift, different every video. The layout does not change - each block
// moves as one - but no two videos are pixel-identical, which is the point when the same
// tutorial and the same logos go out hundreds of times.
func jitter(_ key: String) -> (Double, Double) {
    guard let v = spec[key] as? [Any], v.count == 2 else { return (0, 0) }
    return (Double("\(v[0])") ?? 0, Double("\(v[1])") ?? 0)
}
let jLine  = jitter("jitter_line")
let jCards = jitter("jitter_cards")
let jMoney = jitter("jitter_money")
let claudeImg = NSImage(contentsOfFile: spec["claude_logo"] as? String ?? "")
let shortsImg = NSImage(contentsOfFile: spec["shorts_logo"] as? String ?? "")
// Read through NSNumber, so 2 and 2.0 in the spec mean the same thing. Clamped rather than
// trusted: a zero would draw nothing at all and say nothing about why.
let claudeScale = max(0.1, min(3.0, (spec["claude_logo_scale"] as? NSNumber)?.doubleValue ?? 1.0))
let shortsScale = max(0.1, min(3.0, (spec["shorts_logo_scale"] as? NSNumber)?.doubleValue ?? 1.0))

// The farm format draws no logos, so it is allowed to be given none. Every other format needs
// them and still says so rather than rendering something silently wrong.
let blank = NSImage(size: NSSize(width: 1, height: 1))
guard let claude = claudeImg ?? (isFarm ? blank : nil),
      let shorts = shortsImg ?? (isFarm ? blank : nil) else {
    FileHandle.standardError.write("render_hook: could not open one of the logo images\n".data(using: .utf8)!)
    exit(1)
}

// Work out the fixed slots ONCE, so every piece lands in the same place in every frame.
//
// Claude is first and on the left again, 9 Sep 2026. Pool names remain unchanged.
let plusFont = loadFont(fontPath, PLUS_SIZE)
let plusW    = NSAttributedString(string: "+", attributes: attrs(plusFont)).size().width
let cW = logoWidth(claude, claudeScale), sW = logoWidth(shorts, shortsScale)
let totalW = sW + CARD_GAP + plusW + CARD_GAP + cW
let claudeX = (W - totalW) / 2
let plusX   = claudeX + cW + CARD_GAP
let shortsX = plusX + plusW + CARD_GAP

// ---- the four overlays ------------------------------------------------------
// The "compare" format has no money card, and "card" has no opening line - but every one of
// the four files is still written, blank where it is not used. make_videos.py hands all four
// to ffmpeg every time and switches them on and off by their timings; a missing file would
// fail the whole render instead of simply drawing nothing.
save(frame { if !isCard { drawText(lineText, loadFont(fontPath, LINE_SIZE),
                                   topY: LINE_TOP - lineRise, dx: jLine.0, dy: jLine.1) } },
     outDir + "/line.png")

// THE "+" IS DRAWN WITH WHICHEVER LOGO ARRIVES SECOND, and `make_videos.beat_grid` decides
// which that is - it arrives in the spec as `plus_with`, worked out from the two times
// themselves so the drawing and the timing cannot disagree. On the line format the second
// logo appears two beats after the first, and a "+" that came in with the FIRST one would
// hang in the middle of the frame with empty space beside it for two beats, looking like
// something failed to load. This is what keeps the build-up reading as "one thing, plus
// another thing" whichever way round the two are.
//
// IT NAMES A PICTURE, NOT A PLACE - "claude" or "shorts". It said "left"/"right" for a few
// hours on 7 Sep 2026 and then the two pictures swapped sides, which would have left the word
// meaning the opposite of what it says. Nothing in this file may name a logo by where it is
// drawn.
//
// Its position never moves. `plusX` is worked out once, above, from both pictures' widths,
// and it stays centred on the CARD rather than on the bigger of the two - see `drawLogo`.
let plusWithClaude = (spec["plus_with"] as? String ?? "shorts") == "claude"
func drawPlus() {
    for style in [outlineAttrs(plusFont), fillAttrs(plusFont)] {
        let a = NSAttributedString(string: "+", attributes: style)
        a.draw(at: NSPoint(x: plusX + jCards.0,
                           y: H - CARD_BOTTOM - jCards.1 + cardRise
                              + (CARD_HEIGHT * min(claudeScale, shortsScale) - a.size().height) / 2))
    }
}

save(frame {
    if !isCompare {
        if plusWithClaude { drawPlus() }
        _ = drawLogo(claude, x: claudeX + jCards.0, dy: jCards.1 - cardRise, scale: claudeScale)
    }
}, outDir + "/claude.png")

save(frame {
    if !isCompare {
        if !plusWithClaude { drawPlus() }
        _ = drawLogo(shorts, x: shortsX + jCards.0, dy: jCards.1 - cardRise, scale: shortsScale)
    }
}, outDir + "/plusshorts.png")

save(frame { if !isCompare { drawText(moneyText, loadFont(fontPath, MONEY_SIZE),
                                      topY: MONEY_TOP - moneyRise,
                                      dx: jMoney.0, dy: jMoney.1) } },
     outDir + "/money.png")

print("ok")
