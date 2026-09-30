// to_sdr.swift - turn an HDR clip off the phone into an ordinary one.
//
// Why this exists. Steven's iPhone films in HDR: 10-bit, BT.2020 primaries, HLG transfer.
// CapCut quietly tone-maps that to ordinary SDR when he exports, which is why every clip that
// came out of CapCut looks right. A clip taken straight off the phone does not get that
// treatment, and when it is cut into a video next to SDR footage the result is pale, bright
// and washed out - measured, average brightness 119 against 98 for the same frame in his own
// finished video, with the green channel 24 points high.
//
// ffmpeg cannot fix it here. The tone-mapping filters need `zscale`, and the Homebrew build on
// this Mac is a slim one with no libzimg - checked, it has eight --enable-lib flags and that is
// not one of them. `colorspace` refuses HLG outright ("Unsupported input transfer
// characteristics 18"), and `tonemap` without a linearising step produced a frame at brightness
// 38 against the correct 98. Nor does `avconvert`, which copies the HDR tags straight through.
//
// macOS does it properly, so macOS does it - the same call this project already makes for
// captions and for reading text off an image. Setting the colour properties on an
// AVMutableVideoComposition is what makes Core Video convert rather than copy.
//
//   to_sdr <in> <out>        writes an SDR H.264 .mp4, audio untouched

import Foundation
import AVFoundation

let args = CommandLine.arguments
guard args.count > 2 else {
    FileHandle.standardError.write("usage: to_sdr <in> <out>\n".data(using: .utf8)!)
    exit(2)
}
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
try? FileManager.default.removeItem(at: outURL)

let asset = AVURLAsset(url: inURL)
let sem = DispatchSemaphore(value: 0)
var failure: String? = nil

func fail(_ m: String) -> Never {
    FileHandle.standardError.write((m + "\n").data(using: .utf8)!)
    exit(1)
}

// propertiesOf keeps the size, the frame rate and - importantly - the rotation the phone
// recorded, so a portrait clip stays portrait instead of being written out on its side.
let comp = AVMutableVideoComposition(propertiesOf: asset)
comp.colorPrimaries = AVVideoColorPrimaries_ITU_R_709_2
comp.colorTransferFunction = AVVideoTransferFunction_ITU_R_709_2
comp.colorYCbCrMatrix = AVVideoYCbCrMatrix_ITU_R_709_2

guard let export = AVAssetExportSession(asset: asset,
                                        presetName: AVAssetExportPresetHighestQuality) else {
    fail("to_sdr: could not start an export session")
}
export.videoComposition = comp
export.outputURL = outURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true

export.exportAsynchronously {
    if export.status != .completed {
        failure = export.error?.localizedDescription ?? "export did not finish"
    }
    sem.signal()
}
if sem.wait(timeout: .now() + 900) == .timedOut {
    fail("to_sdr: timed out")
}
if let f = failure { fail("to_sdr: " + f) }
print(outURL.path)
