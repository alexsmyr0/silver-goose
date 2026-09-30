// Person segmentation for ordinary backgrounds. Pump's black-background refinements
// must not run here: they would mark a bright room as part of the presenter.
import Foundation
import CoreImage
import Vision

let args = CommandLine.arguments
guard args.count == 3, let w = Int(args[1]), let h = Int(args[2]), w > 0, h > 0 else { exit(2) }
let input = FileHandle.standardInput, output = FileHandle.standardOutput
let context = CIContext(options: [.useSoftwareRenderer: false])
let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = .accurate
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
var frames = 0, found = 0
while true {
    var data = Data()
    while data.count < w*h*4 {
        guard let chunk = try? input.read(upToCount: w*h*4-data.count), !chunk.isEmpty else { break }
        data.append(chunk)
    }
    if data.isEmpty { break }
    if data.count != w*h*4 { exit(3) }
    var maybe: CVPixelBuffer?
    let attrs = [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary
    guard CVPixelBufferCreate(kCFAllocatorDefault,w,h,kCVPixelFormatType_32BGRA,attrs,&maybe) == kCVReturnSuccess,
          let buffer = maybe else { exit(4) }
    CVPixelBufferLockBaseAddress(buffer, [])
    data.withUnsafeBytes { source in
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        for y in 0..<h { memcpy(CVPixelBufferGetBaseAddress(buffer)!.advanced(by:y*stride),source.baseAddress!.advanced(by:y*w*4),w*4) }
    }
    CVPixelBufferUnlockBaseAddress(buffer, [])
    do {
        try VNImageRequestHandler(cvPixelBuffer:buffer,options:[:]).perform([request])
        var matte = Data(count:w*h)
        if let mask = request.results?.first?.pixelBuffer {
            let mw = CVPixelBufferGetWidth(mask), mh = CVPixelBufferGetHeight(mask)
            let image = CIImage(cvPixelBuffer:mask).transformed(by:CGAffineTransform(scaleX:CGFloat(w)/CGFloat(mw),y:CGFloat(h)/CGFloat(mh)))
            matte.withUnsafeMutableBytes { bytes in
                context.render(image,toBitmap:bytes.baseAddress!,rowBytes:w,bounds:CGRect(x:0,y:0,width:w,height:h),format:.L8,colorSpace:nil)
            }
            if matte.contains(where: { $0 > 128 }) { found += 1 }
        }
        output.write(matte)
    } catch {
        FileHandle.standardError.write(Data("Could not remove the presenter's background.\n".utf8)); exit(5)
    }
    frames += 1
}
if frames == 0 || found == 0 {
    FileHandle.standardError.write(Data("No person found. Check the clip or choose Green screen / Keep background.\n".utf8)); exit(6)
}
