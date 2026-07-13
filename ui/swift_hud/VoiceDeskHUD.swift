import AppKit
import CoreText
import SwiftUI

private struct ProviderColumn: Identifiable {
    let id = UUID()
    let title: String
    let lines: [String]
}

/// One calendar todo pushed from the Python store. `date` is "yyyy-MM-dd";
/// `time` is "HH:MM" or "" when the todo has no deadline.
private struct TodoItem: Identifiable, Equatable {
    let id: String
    let date: String
    let time: String
    let text: String
    let done: Bool
}

private struct HUDSnapshot {
    var visible = true
    var visual = "idle_collapsed"
    var state = "idle"
    var stateLabel = ""
    var stateColor = NSColor.white
    var baseWidth: CGFloat = 340
    var baseHeight: CGFloat = 64
    var providerSummary = ""
    var providerColumns: [ProviderColumn] = []
    var transcript = ""
    var micBars: [CGFloat] = []
    var showClock = true
    var showMedia = true
    var clockTime = ""
    var clockDate = ""
    var mediaTitle = ""
    var mediaArtist = ""
    var mediaPlaying = false
    var mediaArtwork = ""     // base64 PNG
    var mediaPlayerApp = ""   // "Music" | "Spotify" | "" — which app to control
    var mediaPosition: Double = 0   // current playback position, seconds
    var mediaDuration: Double = 0   // track length, seconds (0 = unknown)
    var routines: [String] = []
    var commandSuggestions: [String] = []
    var battery = ""
    var batteryPercent: Int? = nil
    var batteryCharging = false
    var interactionSounds = true
    var inputPrompt = ""
    var inputPrefill = ""
    var todos: [TodoItem] = []
    var calMonthOffset = 0
    var calSelectedDate = ""   // "yyyy-MM-dd"
    var nextEventTitle = ""
    var nextEventTime = ""
    var keyboardActive = false   // inline todo field wants the panel keyed

    init() {}

    init(_ raw: [String: Any]) {
        visible = bool(raw["visible"], true)
        visual = string(raw["visual"], "idle_collapsed")
        state = string(raw["state"], "idle")
        stateLabel = string(raw["stateLabel"], "")
        stateColor = color(raw["stateColor"], NSColor.white)
        baseWidth = cgFloat(raw["baseWidth"], 340)
        baseHeight = cgFloat(raw["baseHeight"], 64)
        providerSummary = string(raw["providerSummary"], "")
        transcript = string(raw["transcript"], "")
        micBars = cgFloatArray(raw["micBars"])
        showClock = bool(raw["showClock"], true)
        showMedia = bool(raw["showMedia"], true)
        clockTime = string(raw["clockTime"], "")
        clockDate = string(raw["clockDate"], "")
        mediaTitle = string(raw["mediaTitle"], "")
        mediaArtist = string(raw["mediaArtist"], "")
        mediaPlaying = bool(raw["mediaPlaying"], false)
        mediaArtwork = string(raw["mediaArtwork"], "")
        mediaPlayerApp = string(raw["mediaPlayerApp"], "")
        mediaPosition = Double(cgFloat(raw["mediaPosition"], 0))
        mediaDuration = Double(cgFloat(raw["mediaDuration"], 0))
        routines = stringArray(raw["routines"])
        commandSuggestions = stringArray(raw["commandSuggestions"])
        battery = string(raw["battery"], "")
        batteryPercent = (raw["batteryPercent"] as? NSNumber)?.intValue
        batteryCharging = bool(raw["batteryCharging"], false)
        interactionSounds = bool(raw["interactionSounds"], true)
        inputPrompt = string(raw["inputPrompt"], "")
        inputPrefill = string(raw["inputPrefill"], "")
        calMonthOffset = Int(cgFloat(raw["calMonthOffset"], 0))
        calSelectedDate = string(raw["calSelectedDate"], "")
        nextEventTitle = string(raw["nextEventTitle"], "")
        nextEventTime = string(raw["nextEventTime"], "")
        keyboardActive = bool(raw["keyboardActive"], false)

        if let arr = raw["todos"] as? [[String: Any]] {
            todos = arr.map {
                TodoItem(
                    id: string($0["id"], ""),
                    date: string($0["date"], ""),
                    time: string($0["time"], ""),
                    text: string($0["text"], ""),
                    done: bool($0["done"], false)
                )
            }
        }

        if let cols = raw["providerColumns"] as? [[String: Any]] {
            providerColumns = cols.map {
                ProviderColumn(
                    title: string($0["title"], ""),
                    lines: stringArray($0["lines"])
                )
            }
        }
    }
}

private func string(_ value: Any?, _ fallback: String) -> String {
    value as? String ?? fallback
}

private func bool(_ value: Any?, _ fallback: Bool) -> Bool {
    if let value = value as? Bool { return value }
    if let value = value as? NSNumber { return value.boolValue }
    return fallback
}

private func cgFloat(_ value: Any?, _ fallback: CGFloat) -> CGFloat {
    if let value = value as? CGFloat { return value }
    if let value = value as? NSNumber { return CGFloat(value.doubleValue) }
    if let value = value as? Double { return CGFloat(value) }
    return fallback
}

private func cgFloatArray(_ value: Any?) -> [CGFloat] {
    guard let values = value as? [Any] else { return [] }
    return values.map { cgFloat($0, 0) }
}

private func stringArray(_ value: Any?) -> [String] {
    guard let values = value as? [Any] else { return [] }
    return values.compactMap { $0 as? String }
}

private func color(_ value: Any?, _ fallback: NSColor) -> NSColor {
    guard let values = value as? [Any], values.count >= 3 else { return fallback }
    let red = cgFloat(values[0], 1)
    let green = cgFloat(values[1], 1)
    let blue = cgFloat(values[2], 1)
    let alpha = values.count >= 4 ? cgFloat(values[3], 1) : 1
    return NSColor(calibratedRed: red, green: green, blue: blue, alpha: alpha)
}

private final class EventEmitter {
    private let lock = NSLock()

    func emit(_ event: String, _ extra: [String: Any] = [:]) {
        var payload = extra
        payload["event"] = event
        guard var data = try? JSONSerialization.data(withJSONObject: payload) else {
            return
        }
        data.append(contentsOf: [0x0A])
        lock.lock()
        FileHandle.standardOutput.write(data)
        lock.unlock()
    }

    func log(_ message: String) {
        guard let data = (message + "\n").data(using: .utf8) else { return }
        FileHandle.standardError.write(data)
    }
}

private struct VisualSize {
    let width: CGFloat
    let totalHeight: CGFloat
    let contentHeight: CGFloat
    // Width of the physical notch on this screen (0 when the display has none).
    // The idle_peek "ears" use it to reserve a center gap so their glanceable
    // content (clock / battery) never hides behind the hardware notch.
    var notchWidth: CGFloat = 0
    // Height of the top "ears" row on a physical-notch strip (the hardware notch
    // height). >0 marks a notch-strip layout: hover + active states sit at
    // exactly this height and flank the notch, growing only left/right. 0 means
    // no notch strip (collapsed/pinned, or a notchless display's downward look).
    var notchHeight: CGFloat = 0
}

/// The collapsed idle pill hides *behind* the physical notch: sized 2pt inside
/// each edge so anti-aliasing/rounding never lets a black "ear" peek past the
/// hardware notch. Hover (idle_peek) then grows it out; see visualSize.
private let collapsedNotchInset: CGFloat = 4
/// Collapsed idle size on a display with NO physical notch. A hardware notch
/// costs zero space (it hides behind the bezel); simulating a big notch on
/// notchless hardware would instead permanently occupy the top-center. So idle
/// here is a small, low handle flush to the top edge — enough to signal "the app
/// is here" and act as a hover target — that grows to the peek/panel on hover.
private let collapsedHandleSize = CGSize(width: 110, height: 7)
/// Hover peek width on a display with NO physical notch: the "ears" metaphor
/// needs a notch to flank, so without one the peek is a compact centered chip
/// (clock · battery) whose pill hugs that content instead of a wide empty bar.
private let compactPeekWidth: CGFloat = 210
/// Extra height added BELOW the physical-notch strip so an active state can show
/// the recognized command transcript. It sits under the notch line — the one
/// place text can grow into without tucking behind the Dynamic Island.
private let transcriptStripHeight: CGFloat = 34
/// Visuals that, on a physical-notch display, render as a notch-height strip
/// growing only left/right (never down behind the notch). Everything else keeps
/// its requested size. Active states may still grow DOWN for a transcript (see
/// transcriptStripHeight) — that row lands beneath the notch, so it stays clear.
private let notchStripVisuals: Set<String> = [
    "idle_peek", "listening", "processing", "executing", "success", "error", "danger_confirm",
]
/// The subset of notchStripVisuals whose transcript row (when present) is allowed
/// to expand the strip downward.
private let transcriptStripVisuals: Set<String> = [
    "listening", "processing", "executing", "success", "error",
]
/// Design tokens — a single source for the HUD's type scale, 4pt spacing
/// rhythm, corner radii, and the surface/text colors that sit on the flat
/// black pill. Every view stays on these values so the panel reads as one
/// deliberate system instead of ad-hoc sizes and opacities.
private enum T {
    // 4pt spacing rhythm
    static let space1: CGFloat = 4
    static let space2: CGFloat = 8
    static let space3: CGFloat = 12
    static let space4: CGFloat = 16
    static let pinnedHeaderOverlayTop: CGFloat = 10

    // corner radii
    static let rCard: CGFloat = 13
    static let rArt: CGFloat = 9

    // text ink on the black pill (a fixed opacity ladder, not SwiftUI's
    // theme-dependent .secondary/.tertiary which drift on a custom surface)
    static let ink = Color.white
    static let ink2 = Color.white.opacity(0.62)
    static let ink3 = Color.white.opacity(0.40)

    // card surface: a faint top-lit gradient + hairline reads as gentle
    // dimensionality on flat black — the premium-dark-UI look — without the
    // outer "silver border" that a stroke on the pill itself would create.
    static let cardTop = Color.white.opacity(0.08)
    static let cardBottom = Color.white.opacity(0.035)
    static let hairline = Color.white.opacity(0.08)
    static let control = Color.white.opacity(0.13)

    // Pretendard is the single typeface for the whole HUD (Korean + Latin in
    // one family), so text reads as one system. Every `.font(...)` in the HUD
    // routes through `T.font` / the tokens below — never Font.system — EXCEPT
    // SF Symbol images, which must stay on Font.system since Pretendard has no
    // symbol glyphs. We name an explicit per-weight PostScript face rather than
    // Font.custom(...).weight(...) because SwiftUI's synthetic weighting on a
    // variable font is unreliable. If the face isn't registered, Font.custom
    // falls back to the system font and the HUD still renders.
    static func font(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        Font.custom(pretendardFace(weight), size: size)
    }

    private static func pretendardFace(_ w: Font.Weight) -> String {
        switch w {
        case .ultraLight, .thin: return "PretendardVariable-Thin"
        case .light:             return "PretendardVariable-Light"
        case .medium:            return "PretendardVariable-Medium"
        case .semibold:          return "PretendardVariable-SemiBold"
        case .bold:              return "PretendardVariable-Bold"
        case .heavy:             return "PretendardVariable-ExtraBold"
        case .black:             return "PretendardVariable-Black"
        default:                 return "PretendardVariable-Regular"
        }
    }

    // type scale — one ladder, shared by every text surface
    static let display = font(21, .semibold)
    static let title   = font(13.5, .semibold)
    static let body    = font(12.5, .medium)
    static let label   = font(10.5, .semibold)
    static let caption = font(10.5, .medium)

    // one spring for every surface transition, so motion feels of a piece
    static let spring = Animation.spring(response: 0.4, dampingFraction: 0.82)
}

/// Debug/preview override: `VOICEDESK_HUD_FAKE_NOTCH="WIDTHxHEIGHT"` (points,
/// e.g. "200x37") makes visualSize treat every screen as having a physical notch
/// of that size, so the notched-display layout can be previewed on hardware that
/// has none. Returns nil (no effect) when unset or malformed.
private func fakeNotchOverride() -> (width: CGFloat, height: CGFloat)? {
    guard let raw = ProcessInfo.processInfo.environment["VOICEDESK_HUD_FAKE_NOTCH"],
          !raw.isEmpty else { return nil }
    let parts = raw.lowercased().split(separator: "x")
    guard parts.count == 2,
          let w = Double(parts[0]), let h = Double(parts[1]),
          w > 0, h > 0 else { return nil }
    return (CGFloat(w), CGFloat(h))
}

private func visualSize(for snapshot: HUDSnapshot, screen: NSScreen) -> VisualSize {
    let baseWidth = snapshot.baseWidth
    let baseHeight = snapshot.baseHeight
    var topInset = screen.safeAreaInsets.top

    // Physical notch width on this screen (0 when the display has none), carried
    // on every VisualSize so views can reason about the hardware notch.
    let leftWidth = screen.auxiliaryTopLeftArea?.width ?? 0
    let rightWidth = screen.auxiliaryTopRightArea?.width ?? 0
    var hasNotch = topInset > 0 && leftWidth > 0 && rightWidth > 0
    var notchWidth = hasNotch ? screen.frame.width - leftWidth - rightWidth : 0

    // Simulate a notch on notchless hardware for previewing the strip layout.
    if let fake = fakeNotchOverride() {
        topInset = fake.height
        notchWidth = fake.width
        hasNotch = true
    }

    if snapshot.visual == "idle_collapsed" {
        if hasNotch, notchWidth > 0 {
            // Physical notch present: tuck the collapsed pill just inside it so
            // idle reads as the bare hardware notch. Hover expands to idle_peek.
            let width = notchWidth - collapsedNotchInset
            return VisualSize(
                width: width,
                totalHeight: topInset,
                contentHeight: topInset,
                notchWidth: notchWidth
            )
        }
        // No physical notch: a small top-edge handle rather than a permanent
        // black block, since there is no bezel to hide an idle notch behind.
        return VisualSize(
            width: collapsedHandleSize.width,
            totalHeight: collapsedHandleSize.height,
            contentHeight: collapsedHandleSize.height
        )
    }

    if hasNotch, notchWidth > 0, notchStripVisuals.contains(snapshot.visual) {
        // Physical notch present: hover + active states sit at exactly the notch
        // height and flank it left/right, so nothing hides behind the hardware
        // notch. An active state with a recognized transcript grows DOWNWARD by
        // transcriptStripHeight — that row sits below the notch line and stays
        // fully visible; without a notch this whole branch is skipped and the
        // original downward layout (baseHeight) is kept.
        let showsTranscript =
            transcriptStripVisuals.contains(snapshot.visual) && !snapshot.transcript.isEmpty
        let total = showsTranscript ? topInset + transcriptStripHeight : topInset
        return VisualSize(
            width: baseWidth,
            totalHeight: total,
            contentHeight: total,
            notchWidth: notchWidth,
            notchHeight: topInset
        )
    }

    if snapshot.visual == "idle_peek", !hasNotch {
        // No hardware notch to flank: shrink the peek to a compact centered chip
        // instead of a wide bar with an empty middle.
        return VisualSize(
            width: compactPeekWidth,
            totalHeight: baseHeight,
            contentHeight: baseHeight
        )
    }

    return VisualSize(
        width: baseWidth,
        totalHeight: baseHeight,
        contentHeight: baseHeight,
        notchWidth: notchWidth
    )
}

private func rectNearlyEqual(_ lhs: NSRect, _ rhs: NSRect, tolerance: CGFloat = 0.5) -> Bool {
    abs(lhs.origin.x - rhs.origin.x) <= tolerance
        && abs(lhs.origin.y - rhs.origin.y) <= tolerance
        && abs(lhs.size.width - rhs.size.width) <= tolerance
        && abs(lhs.size.height - rhs.size.height) <= tolerance
}

private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }
}

/// Bottom-only rounding for the collapsed pill, which fuses flush against
/// the physical notch/menu-bar edge above it.
private struct BottomRoundedRect: Shape {
    var radius: CGFloat

    func path(in rect: CGRect) -> Path {
        let r = min(radius, min(rect.width, rect.height) / 2)
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - r, y: rect.maxY),
            control: CGPoint(x: rect.maxX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX + r, y: rect.maxY))
        path.addQuadCurve(
            to: CGPoint(x: rect.minX, y: rect.maxY - r),
            control: CGPoint(x: rect.minX, y: rect.maxY)
        )
        path.closeSubpath()
        return path
    }
}

/// Capsule (fully-rounded pill) button, matching NotchNook's "prefer round
/// buttons" style rather than macOS's default rounded-rectangle bezel.
private struct CapsuleButtonStyle: ButtonStyle {
    var prominent: Bool = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(T.font(12, .semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 7)
            .background(
                Capsule(style: .continuous)
                    .fill(prominent ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(Color.white.opacity(0.13)))
                    .overlay {
                        if !prominent {
                            Capsule(style: .continuous)
                                .strokeBorder(Color.white.opacity(0.08), lineWidth: 0.75)
                        }
                    }
            )
            .foregroundStyle(prominent ? Color.white : Color.white.opacity(0.92))
            .scaleEffect(configuration.isPressed ? 0.93 : 1.0)
            .animation(.spring(response: 0.25, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

/// SF Symbol per agent state — replaces emoji-in-string labels with crisp
/// vector glyphs that tint with the state's accent color.
private func stateSymbol(_ state: String) -> String {
    switch state {
    case "listening": return "waveform"
    case "processing": return "sparkles"
    case "executing": return "bolt.fill"
    case "success": return "checkmark.circle.fill"
    case "error": return "exclamationmark.circle.fill"
    case "danger_confirm": return "exclamationmark.triangle.fill"
    default: return "circle.fill"
    }
}

/// Best-guess SF Symbol + tint for a command-palette suggestion, keyed off
/// words in the (Korean) command text — so a "볼륨" row reads as a speaker, a
/// "날씨" row as weather, etc., instead of every row wearing the same generic
/// glyph. Falls back to a neutral sparkle for anything unrecognized.
private func suggestionIcon(_ text: String) -> (symbol: String, tint: Color) {
    let t = text.lowercased()
    func has(_ words: [String]) -> Bool { words.contains { t.contains($0) } }
    if has(["사파리", "safari", "브라우저", "검색", "구글", "인터넷"]) {
        return ("safari", Color(red: 0.36, green: 0.68, blue: 1.0))
    }
    if has(["볼륨", "소리", "음량", "무음", "뮤트"]) {
        return ("speaker.wave.2.fill", Color(red: 0.98, green: 0.62, blue: 0.35))
    }
    if has(["날씨", "기온", "비", "미세먼지"]) {
        return ("cloud.sun.fill", Color(red: 0.45, green: 0.78, blue: 0.95))
    }
    if has(["음악", "노래", "재생", "플레이", "spotify", "음원"]) {
        return ("music.note", Color(red: 0.95, green: 0.45, blue: 0.75))
    }
    if has(["메모", "작성", "적어", "노트", "기록"]) {
        return ("note.text", Color(red: 0.98, green: 0.80, blue: 0.35))
    }
    if has(["일정", "캘린더", "알림", "약속", "스케줄"]) {
        return ("calendar", Color(red: 0.98, green: 0.45, blue: 0.45))
    }
    if has(["메일", "이메일", "mail"]) {
        return ("envelope.fill", Color(red: 0.55, green: 0.72, blue: 1.0))
    }
    if has(["열어", "실행", "켜", "앱", "실행해"]) {
        return ("square.grid.2x2.fill", Color(red: 0.62, green: 0.78, blue: 0.55))
    }
    return ("sparkles", Color(red: 0.72, green: 0.60, blue: 1.0))
}

/// Borderless windows refuse key status by default; the notch text-input
/// field needs it to receive keystrokes.
private final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

/// Three tiny bars bouncing forever — the classic "audio playing" glyph.
/// A pink-to-cyan gradient (rather than a flat color) is what makes it read
/// as a lively music indicator instead of a generic loading spinner.
private struct EqualizerGlyph: View {
    @State private var up = false

    private var gradient: LinearGradient {
        LinearGradient(colors: [.pink, .purple, .cyan], startPoint: .bottom, endPoint: .top)
    }

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<3, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(gradient)
                    .frame(width: 2.5, height: up ? [10, 5, 8][i] : [4, 9, 5][i])
                    .animation(
                        .easeInOut(duration: 0.45).repeatForever(autoreverses: true).delay(Double(i) * 0.12),
                        value: up
                    )
            }
        }
        .frame(height: 10, alignment: .bottom)
        .onAppear { up = true }
    }
}

/// Playback scrubber for the now-playing card: a draggable progress track with
/// elapsed / total time labels. The backend only pushes a fresh position every
/// widget tick (~5s), so between ticks we interpolate from a wall-clock anchor
/// to keep the fill gliding smoothly while playing. Dragging previews locally
/// and emits `mediaSeek` (seconds) on release.
private struct MediaSeekBar: View {
    let position: Double
    let duration: Double
    let playing: Bool
    let onSeek: (Double) -> Void

    // Anchor for interpolation: `basePosition` was the true position at `baseTime`.
    @State private var basePosition: Double = 0
    @State private var baseTime: Date = Date()
    // Non-nil (0…1) only while the user is scrubbing.
    @State private var dragFrac: Double? = nil

    private let knob: CGFloat = 10
    private let trackHeight: CGFloat = 4

    var body: some View {
        // Tick often while playing for a smooth fill; idle otherwise.
        TimelineView(.periodic(from: .now, by: playing ? 0.5 : 10)) { context in
            let shown = dragFrac.map { $0 * duration } ?? interpolated(now: context.date)
            let frac = duration > 0 ? min(max(shown / duration, 0), 1) : 0
            VStack(spacing: 3) {
                GeometryReader { geo in
                    bar(width: geo.size.width, frac: frac)
                }
                .frame(height: knob)
                HStack {
                    Text(timeString(shown))
                    Spacer(minLength: 0)
                    Text(timeString(duration))
                }
                .font(T.font(9.5, .medium))
                .foregroundStyle(T.ink3)
                .monospacedDigit()
            }
        }
        .onAppear { basePosition = position; baseTime = Date() }
        .onChange(of: position) {
            // A fresh backend snapshot re-anchors us (skip while scrubbing).
            if dragFrac == nil { basePosition = position; baseTime = Date() }
        }
        .onChange(of: playing) {
            basePosition = interpolated(now: Date()); baseTime = Date()
        }
    }

    private func interpolated(now: Date) -> Double {
        guard playing else { return basePosition }
        let advanced = basePosition + now.timeIntervalSince(baseTime)
        return duration > 0 ? min(advanced, duration) : advanced
    }

    private func bar(width: CGFloat, frac: Double) -> some View {
        let usable = max(width - knob, 1)
        let filled = knob / 2 + usable * CGFloat(frac)
        return ZStack(alignment: .leading) {
            Capsule().fill(T.control)
                .frame(height: trackHeight)
            Capsule()
                .fill(LinearGradient(colors: [.pink, .purple],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(width: filled, height: trackHeight)
            Circle()
                .fill(Color.white)
                .frame(width: knob, height: knob)
                .shadow(color: .black.opacity(0.35), radius: 1.5, y: 0.5)
                .offset(x: usable * CGFloat(frac))
        }
        .frame(height: knob)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { g in
                    dragFrac = fraction(at: g.location.x, usable: usable)
                }
                .onEnded { g in
                    let f = fraction(at: g.location.x, usable: usable)
                    dragFrac = nil
                    basePosition = f * duration
                    baseTime = Date()
                    onSeek(basePosition)
                }
        )
    }

    private func fraction(at x: CGFloat, usable: CGFloat) -> Double {
        min(max(Double((x - knob / 2) / usable), 0), 1)
    }

    private func timeString(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

/// Month-grid calendar shown in the pinned panel beneath the clock. Backed by
/// the real todo store: `todos` (pushed from Python) drives the per-day dots
/// and the selected-day list. Month browsing and day selection live in Python
/// (`monthOffset` / `selectedDate`) so they survive the text-input round-trip
/// an add/edit does; taps emit events the Python side turns back into props.
private struct CalendarWidget: View {
    let todos: [TodoItem]
    let monthOffset: Int
    let selectedDate: String   // "yyyy-MM-dd"
    let emit: (String, [String: Any]) -> Void

    // Which todo's edit/delete popup is open (nil = none). Transient UI state,
    // so it stays local rather than round-tripping to Python.
    @State private var actionTodo: TodoItem? = nil

    // Inline entry state. The "할 일 추가" row becomes a text field in place
    // (`adding`), or a todo's row does (`editingID`) — never both at once. The
    // field's text lives in `draft`, and `fieldFocused` drives keyboard focus.
    // Entering either mode emits `inlineEditBegin` so the Python side keys the
    // panel window; leaving emits `inlineEditEnd`.
    @State private var adding = false
    @State private var editingID: String? = nil
    @State private var draft = ""
    @FocusState private var fieldFocused: Bool

    private let accent = Color(red: 0.40, green: 0.72, blue: 1.0)
    private let weekdayNames = ["일", "월", "화", "수", "목", "금", "토"]

    // Sunday-first Gregorian, matching macOS Korean calendars.
    private var cal: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.firstWeekday = 1
        return c
    }

    // "yyyy-MM-dd" formatter shared with the Python store's date keys.
    private static let iso: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var startOfThisMonth: Date {
        let now = Date()
        return cal.date(from: cal.dateComponents([.year, .month], from: now)) ?? now
    }
    private var displayedMonth: Date {
        cal.date(byAdding: .month, value: monthOffset, to: startOfThisMonth) ?? startOfThisMonth
    }
    private var isCurrentMonth: Bool { monthOffset == 0 }
    private var today: Int { cal.component(.day, from: Date()) }
    private var monthNumber: Int { cal.component(.month, from: displayedMonth) }
    private var daysInMonth: Int {
        cal.range(of: .day, in: .month, for: displayedMonth)?.count ?? 30
    }
    // Weekday of the 1st (1=Sun) minus one = leading blank cells before day 1.
    private var leadingBlanks: Int {
        cal.component(.weekday, from: displayedMonth) - 1
    }

    /// "yyyy-MM-dd" for a day number in the displayed month.
    private func dateString(day: Int) -> String {
        var comps = cal.dateComponents([.year, .month], from: displayedMonth)
        comps.day = day
        guard let date = cal.date(from: comps) else { return "" }
        return Self.iso.string(from: date)
    }

    /// Todos on the currently selected date, timed ones first (ascending).
    private var selectedTodos: [TodoItem] {
        todos.filter { $0.date == selectedDate }
            .sorted { a, b in
                let ka = a.time.isEmpty ? "99:99" : a.time
                let kb = b.time.isEmpty ? "99:99" : b.time
                return ka < kb
            }
    }

    // Fixed geometry so the widget's height never depends on how many todos a
    // day has (or whether the month spans 5 or 6 weeks): the grid always
    // reserves 6 week-rows and the day's list lives in a fixed, scrolling box.
    // This keeps the paired analog clock — which stretches to match — a constant
    // size regardless of content.
    private let dayCellHeight: CGFloat = 30
    private var gridHeight: CGFloat { dayCellHeight * 6 + T.space1 * 5 }
    // Day header + scrolling todo list + the fixed "add todo" row at the bottom.
    private let listBoxHeight: CGFloat = 122

    var body: some View {
        VStack(alignment: .leading, spacing: T.space2) {
            monthHeader
            weekdayRow
            grid
            Rectangle().fill(T.hairline).frame(height: 1)
            selectedList
        }
        // Edit/delete popup floats over the whole widget so it isn't clipped by
        // the scrolling todo box.
        .overlay {
            if let todo = actionTodo {
                todoActionPopup(todo)
            }
        }
    }

    private var monthHeader: some View {
        HStack {
            chevron("chevron.left") { endInlineEdit(); emit("calendarShiftMonth", ["delta": -1]) }
            Spacer()
            Text("\(cal.component(.year, from: displayedMonth))년 \(monthNumber)월")
                .font(T.title)
                .foregroundStyle(T.ink)
            Spacer()
            chevron("chevron.right") { endInlineEdit(); emit("calendarShiftMonth", ["delta": 1]) }
        }
    }

    private var weekdayRow: some View {
        HStack(spacing: 2) {
            ForEach(Array(weekdayNames.enumerated()), id: \.offset) { idx, name in
                Text(name)
                    .font(T.font(9.5, .semibold))
                    .foregroundStyle(weekdayColor(idx).opacity(0.75))
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private var grid: some View {
        let columns = Array(repeating: GridItem(.flexible(), spacing: 2), count: 7)
        let cells: [Int?] = Array(repeating: nil, count: leadingBlanks) + (1...daysInMonth).map { $0 }
        return LazyVGrid(columns: columns, spacing: T.space1) {
            ForEach(Array(cells.enumerated()), id: \.offset) { _, day in
                if let day {
                    dayCell(day)
                } else {
                    Color.clear.frame(height: dayCellHeight)
                }
            }
        }
        // Reserve a full 6-week block so 5-week months don't shrink the grid.
        .frame(height: gridHeight, alignment: .top)
    }

    private func dayCell(_ day: Int) -> some View {
        let col = (leadingBlanks + day - 1) % 7
        let isToday = isCurrentMonth && day == today
        let dateStr = dateString(day: day)
        let isSelected = dateStr == selectedDate
        let hasItems = todos.contains { $0.date == dateStr }
        let numberColor = isToday ? Color.black : weekdayColor(col)
        return VStack(spacing: 2) {
            Text("\(day)")
                .font(T.font(11.5, isToday ? .semibold : .regular))
                .foregroundStyle(numberColor)
                .frame(width: 24, height: 24)
                .background(
                    ZStack {
                        if isToday {
                            Circle().fill(Color.white)
                        } else if isSelected {
                            Circle().stroke(accent, lineWidth: 1.5)
                        }
                    }
                )
            Circle()
                .fill(hasItems ? accent : Color.clear)
                .frame(width: 4, height: 4)
        }
        .frame(maxWidth: .infinity, minHeight: dayCellHeight, maxHeight: dayCellHeight)
        .contentShape(Rectangle())
        // highPriorityGesture so the day tap doesn't fall through to the pill's
        // own tap-to-collapse gesture, mirroring the settings gear.
        .highPriorityGesture(TapGesture().onEnded {
            endInlineEdit()   // switching days cancels any open inline field
            emit("calendarSelectDay", ["date": dateStr])
        })
    }

    private var selectedList: some View {
        VStack(alignment: .leading, spacing: T.space1 + 1) {
            if !selectedDate.isEmpty {
                Text(selectedHeader)
                    .font(T.label)
                    .foregroundStyle(T.ink2)
                // The one variable-size region — capped and scrolled so a busy
                // day can't stretch the widget (and the clock beside it).
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(alignment: .leading, spacing: T.space1 + 1) {
                        if selectedTodos.isEmpty {
                            Text("일정 없음")
                                .font(T.caption)
                                .foregroundStyle(T.ink3)
                        } else {
                            ForEach(selectedTodos) { item in
                                todoRow(item)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: .infinity)
                // Pinned below the scroll so it stays reachable however many
                // todos the day has.
                addTodoField
            } else {
                Text("날짜를 선택하세요")
                    .font(T.caption)
                    .foregroundStyle(T.ink3)
            }
        }
        .frame(maxWidth: .infinity, minHeight: listBoxHeight, maxHeight: listBoxHeight, alignment: .topLeading)
    }

    /// "M월 D일 요일" header for the selected date.
    private var selectedHeader: String {
        guard let date = Self.iso.date(from: selectedDate) else { return "" }
        let m = cal.component(.month, from: date)
        let d = cal.component(.day, from: date)
        let wd = cal.component(.weekday, from: date) - 1   // 0=Sun
        return "\(m)월 \(d)일 \(weekdayNames[wd])요일"
    }

    /// "Add a todo" affordance for the selected day. Tapping turns the row
    /// itself into an inline text field (a trailing "HH:MM" sets an optional
    /// deadline); Enter appends to the store and keeps the field open for the
    /// next entry, while Esc / empty Enter closes it.
    @ViewBuilder
    private var addTodoField: some View {
        if adding {
            HStack(spacing: T.space2) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(accent)
                inlineField(placeholder: "예: 회의 14:00", onSubmit: submitAdd)
            }
            .padding(.horizontal, T.space2)
            .padding(.vertical, T.space1 + 2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: T.rArt - 3, style: .continuous)
                    .fill(T.control)
                    .overlay(
                        RoundedRectangle(cornerRadius: T.rArt - 3, style: .continuous)
                            .strokeBorder(accent.opacity(0.6), lineWidth: 1)
                    )
            )
        } else {
            HStack(spacing: T.space2) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(accent)
                Text("할 일 추가")
                    .font(T.caption)
                    .foregroundStyle(T.ink3)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, T.space2)
            .padding(.vertical, T.space1 + 2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: T.rArt - 3, style: .continuous)
                    .fill(T.control)
            )
            .contentShape(Rectangle())
            .highPriorityGesture(TapGesture().onEnded { startAdding() })
        }
    }

    @ViewBuilder
    private func todoRow(_ item: TodoItem) -> some View {
        HStack(spacing: T.space2) {
            // The circle toggles completion.
            Image(systemName: item.done ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 12))
                .foregroundStyle(item.done ? accent : T.ink3)
                .contentShape(Rectangle())
                .highPriorityGesture(TapGesture().onEnded {
                    emit("todoToggle", ["id": item.id])
                })
            if editingID == item.id {
                // Editing this todo in place: the text becomes a field prefilled
                // with "내용 HH:MM"; Enter saves, Esc cancels.
                inlineField(placeholder: "예: 회의 14:00", onSubmit: { submitEdit(item.id) })
            } else {
                if !item.time.isEmpty {
                    Text(item.time)
                        .font(T.caption)
                        .foregroundStyle(accent)
                        .monospacedDigit()
                }
                // Tapping the text (not the circle) opens the edit/delete popup —
                // scoped to the text so a circle tap only toggles completion.
                Text(item.text)
                    .font(T.caption)
                    .foregroundStyle(item.done ? T.ink3 : T.ink)
                    .strikethrough(item.done, color: T.ink3)
                    .lineLimit(1)
                    .contentShape(Rectangle())
                    .highPriorityGesture(TapGesture().onEnded { actionTodo = item })
                Spacer(minLength: 0)
            }
        }
    }

    /// Edit/delete sheet for a tapped todo. A dimmed backdrop (tap to dismiss)
    /// with a small card; "수정" re-opens text entry, "삭제" removes the todo.
    private func todoActionPopup(_ todo: TodoItem) -> some View {
        ZStack {
            Color.black.opacity(0.55)
                .contentShape(Rectangle())
                .highPriorityGesture(TapGesture().onEnded { actionTodo = nil })
            VStack(spacing: T.space2 + 2) {
                Text(todo.text)
                    .font(T.body)
                    .foregroundStyle(T.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                HStack(spacing: T.space2) {
                    popupButton("pencil", "수정", accent) {
                        startEditing(todo)
                    }
                    popupButton("trash", "삭제", Color(red: 1.0, green: 0.42, blue: 0.42)) {
                        actionTodo = nil
                        emit("todoDelete", ["id": todo.id])
                    }
                }
            }
            .padding(T.space3)
            .frame(maxWidth: 200)
            .background(
                RoundedRectangle(cornerRadius: T.rCard, style: .continuous)
                    .fill(Color(white: 0.14))
                    .overlay(
                        RoundedRectangle(cornerRadius: T.rCard, style: .continuous)
                            .strokeBorder(T.hairline, lineWidth: 1)
                    )
            )
            .padding(.horizontal, T.space2)
        }
    }

    private func popupButton(_ symbol: String, _ label: String, _ tint: Color,
                             _ action: @escaping () -> Void) -> some View {
        HStack(spacing: T.space1) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .semibold))
            Text(label)
                .font(T.font(11.5, .semibold))
        }
        .foregroundStyle(tint)
        .padding(.horizontal, T.space3)
        .padding(.vertical, T.space1 + 3)
        .frame(maxWidth: .infinity)
        .background(Capsule(style: .continuous).fill(tint.opacity(0.15)))
        .contentShape(Capsule())
        .highPriorityGesture(TapGesture().onEnded(action))
    }

    // --- Inline add/edit -------------------------------------------------

    /// The shared inline text field for both add and edit. Emits nothing on its
    /// own — the owner wires `onSubmit`; Esc cancels via `endInlineEdit`. Focus
    /// is grabbed after a short delay so the pinned window has already been
    /// keyed (via `inlineEditBegin`) — otherwise the focus request is dropped.
    private func inlineField(placeholder: String, onSubmit: @escaping () -> Void) -> some View {
        ZStack(alignment: .leading) {
            if draft.isEmpty {
                Text(placeholder)
                    .font(T.caption)
                    .foregroundStyle(T.ink3)
                    .lineLimit(1)
                    .allowsHitTesting(false)
            }
            TextField("", text: $draft)
                .textFieldStyle(.plain)
                .font(T.caption)
                .foregroundStyle(T.ink)
                .tint(accent)
                .lineLimit(1)
                .focused($fieldFocused)
                .onSubmit(onSubmit)
                .onExitCommand { endInlineEdit() }
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { fieldFocused = true }
                }
        }
        .frame(maxWidth: .infinity, minHeight: 18, alignment: .center)
    }

    private func startAdding() {
        editingID = nil
        draft = ""
        adding = true
        emit("inlineEditBegin", [:])
    }

    private func startEditing(_ item: TodoItem) {
        actionTodo = nil
        adding = false
        editingID = item.id
        draft = item.time.isEmpty ? item.text : "\(item.text) \(item.time)"
        emit("inlineEditBegin", [:])
    }

    /// Leave inline entry and let the panel resign key (Python drops the
    /// keyboard focus on `inlineEditEnd`). No-op — and no event — when nothing
    /// was open, so stray day/month taps don't churn the bridge.
    private func endInlineEdit() {
        let wasActive = adding || editingID != nil
        adding = false
        editingID = nil
        draft = ""
        fieldFocused = false
        if wasActive { emit("inlineEditEnd", [:]) }
    }

    private func submitAdd() {
        let text = draft.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else {
            endInlineEdit()   // a stray empty Enter closes the field
            return
        }
        emit("todoAdd", ["date": selectedDate, "text": text])
        // Continuous add: clear and keep focus for the next entry.
        draft = ""
        fieldFocused = true
    }

    private func submitEdit(_ id: String) {
        let text = draft.trimmingCharacters(in: .whitespaces)
        if !text.isEmpty {
            emit("todoUpdate", ["id": id, "text": text])
        }
        endInlineEdit()
    }

    private func weekdayColor(_ col: Int) -> Color {
        switch col {
        case 0: return Color(red: 1.0, green: 0.45, blue: 0.45)  // Sunday
        case 6: return accent                                     // Saturday
        default: return T.ink
        }
    }

    private func chevron(_ symbol: String, _ action: @escaping () -> Void) -> some View {
        Image(systemName: symbol)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(T.ink2)
            .frame(width: 26, height: 26)
            .contentShape(Rectangle())
            .highPriorityGesture(TapGesture().onEnded(action))
    }
}

/// Tall analog clock for the pinned panel's left column, sized to match the
/// calendar's height. Hands are driven by the `HH:MM` string the Python side
/// already pushes for the digital clock, so it needs no separate Swift timer.
/// The next-event line beneath shows today's next upcoming deadline, computed
/// by the Python side from the todo store (empty until one is due).
private struct AnalogClockWidget: View {
    let time: String   // "HH:MM"
    let date: String   // e.g. "7월 13일 일요일"
    let nextTitle: String   // today's next upcoming todo, "" if none
    let nextTime: String    // its "HH:MM" deadline, "" if none

    private let accent = Color(red: 0.40, green: 0.72, blue: 1.0)

    private var hourMinute: (h: Int, m: Int) {
        let parts = time.split(separator: ":")
        let h = parts.count > 0 ? Int(parts[0]) ?? 0 : 0
        let m = parts.count > 1 ? Int(parts[1]) ?? 0 : 0
        return (h, m)
    }
    private var hourAngle: Double { Double(hourMinute.h % 12) * 30 + Double(hourMinute.m) * 0.5 }
    private var minuteAngle: Double { Double(hourMinute.m) * 6 }

    var body: some View {
        VStack(spacing: T.space2 + 2) {
            GeometryReader { geo in
                clockFace(size: min(geo.size.width, geo.size.height))
                    .frame(width: geo.size.width, height: geo.size.height)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if !time.isEmpty {
                Text(time)
                    .font(T.font(15, .semibold))
                    .foregroundStyle(T.ink)
                    .monospacedDigit()
            }

            Rectangle().fill(T.hairline).frame(height: 1)

            nextEventRow
        }
    }

    private func clockFace(size: CGFloat) -> some View {
        ZStack {
            Circle().stroke(T.hairline, lineWidth: 1)
            Circle()
                .fill(Color.white.opacity(0.03))
                .padding(1)

            // Hour ticks — a longer, brighter mark at each quarter.
            ForEach(0..<12, id: \.self) { i in
                Capsule()
                    .fill(i % 3 == 0 ? T.ink2 : T.ink3)
                    .frame(width: i % 3 == 0 ? 2.5 : 1.5, height: i % 3 == 0 ? 9 : 5)
                    .offset(y: -(size / 2 - 8))
                    .rotationEffect(.degrees(Double(i) * 30))
            }

            // Hands: offset up by half their length so the base pivots at the
            // face center, then rotate around that (layout) center.
            Capsule()
                .fill(T.ink)
                .frame(width: 3.5, height: size * 0.26)
                .offset(y: -(size * 0.26) / 2)
                .rotationEffect(.degrees(hourAngle))
            Capsule()
                .fill(T.ink)
                .frame(width: 2.5, height: size * 0.38)
                .offset(y: -(size * 0.38) / 2)
                .rotationEffect(.degrees(minuteAngle))

            Circle().fill(accent).frame(width: 7, height: 7)
        }
        .frame(width: size, height: size)
    }

    private var hasNextEvent: Bool { !nextTitle.isEmpty }

    private var nextEventRow: some View {
        HStack(spacing: T.space2) {
            Image(systemName: "calendar.badge.clock")
                .font(.system(size: 13))
                .foregroundStyle(hasNextEvent ? accent : T.ink3)
            VStack(alignment: .leading, spacing: 1) {
                Text("다음 일정")
                    .font(T.font(8.5, .semibold))
                    .tracking(0.4)
                    .foregroundStyle(T.ink3)
                Text(hasNextEvent ? nextTitle : "예정된 일정 없음")
                    .font(T.caption)
                    .foregroundStyle(hasNextEvent ? T.ink : T.ink3)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            if !nextTime.isEmpty {
                Text(nextTime)
                    .font(T.label)
                    .foregroundStyle(accent)
                    .monospacedDigit()
            }
        }
    }
}

/// Notch text input for long text — voice dictation is unreliable past a few
/// words, so the user confirms/edits here with the keyboard.
private struct TextInputView: View {
    let prompt: String
    let emit: (String, [String: Any]) -> Void
    @State private var draft: String
    @FocusState private var focused: Bool

    init(prompt: String, prefill: String, emit: @escaping (String, [String: Any]) -> Void) {
        self.prompt = prompt
        self.emit = emit
        _draft = State(initialValue: prefill)
    }

    var body: some View {
        VStack(spacing: 8) {
            Text(prompt)
                .font(T.font(11))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            TextField("입력할 내용", text: $draft)
                .font(T.font(13))
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit { emit("textSubmit", ["text": draft]) }
            HStack(spacing: 12) {
                Button("입력") { emit("textSubmit", ["text": draft]) }
                    .buttonStyle(CapsuleButtonStyle(prominent: true))
                    .keyboardShortcut(.defaultAction)
                Button("취소") { emit("textCancel", [:]) }
                    .buttonStyle(CapsuleButtonStyle())
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { focused = true } }
    }
}

private struct HUDView: View {
    let snapshot: HUDSnapshot
    let size: VisualSize
    let surfaceStartSize: CGSize?
    let surfaceContainerSize: CGSize?
    let surfaceAnimationID: Int
    let emit: (String, [String: Any]) -> Void

    @State private var surfaceScaleX: CGFloat = 1
    @State private var surfaceScaleY: CGFloat = 1
    @State private var commandDraft = ""
    @FocusState private var commandFieldFocused: Bool

    private var accent: Color {
        Color(nsColor: snapshot.stateColor)
    }

    private var isCollapsed: Bool { snapshot.visual == "idle_collapsed" }

    private var cornerRadius: CGFloat {
        isCollapsed ? 10 : min(size.contentHeight / 2, 26)
    }

    /// Active states get a faint wash of their accent color bleeding up from
    /// the bottom of the pill — enough to read as "this state has a color"
    /// without competing with the (still legible) black glass surface.
    private var glowsWithAccent: Bool {
        ["listening", "success", "error", "danger_confirm"].contains(snapshot.state)
    }

    @ViewBuilder
    private var pillBackground: some View {
        // Solid black only — no light-colored bevel/highlight stroke. An
        // earlier version added a faint white gradient outline for a "glass"
        // look, but on a real notched display that read as a distracting
        // silver border rather than a bevel, so the pill is flat black now.
        //
        // EVERY visual — collapsed pill AND expanded panels — uses the same
        // bottom-only rounding: the top edge stays square and flush against
        // the notch/menu-bar so the shape reads as the Dynamic Island growing
        // straight down, never as a detached floating card.
        let shape = BottomRoundedRect(radius: cornerRadius)
        ZStack {
            // Fully opaque black: at 0.96 the anti-aliased rounded edge let the
            // background bleed ~4% through, which on a bright wallpaper read as a
            // faint grey rim. Solid black keeps the edge crisp with no halo.
            shape.fill(Color.black)
            if !isCollapsed && glowsWithAccent {
                shape.fill(
                    RadialGradient(
                        colors: [accent.opacity(0.22), .clear],
                        center: .bottom, startRadius: 0, endRadius: size.width * 0.6
                    )
                )
            }
        }
    }

    private var clipShape: AnyShape {
        // Square top, rounded bottom for all states — see pillBackground.
        AnyShape(BottomRoundedRect(radius: cornerRadius))
    }

    private var transitionAnchor: UnitPoint {
        // Hover expansion is the only visual that should read as opening out
        // from the notch's center. Other active panels stay top-attached so the
        // surface still feels fused to the menu-bar edge.
        snapshot.visual == "idle_peek" ? .center : .top
    }

    var body: some View {
        content
            .frame(width: size.width, height: size.contentHeight)
            .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: transitionAnchor)))
            .id(snapshot.visual)   // drives the transition on visual changes
        .frame(width: size.width, height: size.totalHeight)
        .foregroundStyle(.white)
        .background(pillBackground)
        .clipShape(clipShape)
        .overlay {
            if snapshot.visual == "danger_confirm" {
                clipShape.stroke(accent, lineWidth: 1.4)
            }
        }
        // Notch cutout: a pure-black rectangle over the center notch region so
        // NOTHING (accent glow, danger stroke, any content) shows there — only
        // the left/right ears carry color/information, exactly like a real
        // hardware notch. On a genuine notched display this sits behind the
        // physical notch, so it's an invisible no-op. Drawn last so it masks the
        // glow and the danger stroke above.
        .overlay(alignment: .top) {
            if size.notchWidth > 0 && size.notchHeight > 0 {
                Rectangle()
                    .fill(Color.black)
                    .frame(width: size.notchWidth, height: size.notchHeight)
            }
        }
        .overlay(alignment: .top) {
            if snapshot.visual == "idle_pinned" {
                pinnedHeader
                    .padding(.horizontal, T.space4)
                    .padding(.top, T.pinnedHeaderOverlayTop)
            }
        }
        // No shadow of any kind — neither a SwiftUI `.shadow()` nor the AppKit
        // window shadow (`hasShadow = false`). The window shadow used to supply
        // depth, but it drew a soft grey halo around the pill that read as a grey
        // border, so the surface is now a flat black shape with no outline.
        .contentShape(Rectangle())
        .onTapGesture {
            if snapshot.visual != "danger_confirm" && snapshot.visual != "text_input" {
                emit("click", [:])
            }
        }
        // Anchor the morph at the top-center — the notch's own edge. Scaling
        // about this point makes the panel open FROM THE TOP outward to the
        // left, right, and down all at once when growing, and draw straight
        // back up into the notch when shrinking — one motion run forward or
        // backward. The start scale is taken per-axis from the actual size
        // ratio (see notch_hud.py for each visual's dimensions), so the pill
        // opens along whatever proportion that surface calls for.
        .scaleEffect(x: surfaceScaleX, y: surfaceScaleY, anchor: .top)
        // While shrinking, render() holds the window at its old (larger) size so
        // the scaling-down pill isn't clipped; center the pill at the top of
        // that larger box so it retracts straight up toward the notch instead
        // of sticking to a side. When not shrinking the box equals the pill's
        // own size, so this is a no-op.
        .frame(
            width: surfaceContainerSize?.width ?? size.width,
            height: surfaceContainerSize?.height ?? size.totalHeight,
            alignment: .top
        )
        .onAppear {
            startSurfaceAnimationIfNeeded()
        }
        .onChange(of: surfaceAnimationID) {
            startSurfaceAnimationIfNeeded()
        }
        // During the collapsed→peek expansion the growth is carried entirely by
        // the explicit `surfaceScale` spring above. The window frame is snapped
        // to full size at once in render(), so the SwiftUI frame must snap too:
        // letting `.animation` also spring the frame here layered a second,
        // off-center resize on top of the scale — because NSHostingView pins the
        // still-narrow content to its leading edge, that resize read as the pill
        // unfurling to the RIGHT instead of growing straight out of the notch.
        // Suppress the implicit animation on that one render so only the
        // top-anchored scale plays.
        .animation(surfaceStartSize == nil ? T.spring : nil, value: snapshot.visual)
    }

    private func startSurfaceAnimationIfNeeded() {
        guard let start = surfaceStartSize else {
            surfaceScaleX = 1
            surfaceScaleY = 1
            return
        }
        // A start scale ABOVE 1 is allowed: a shrink plays this in reverse,
        // starting oversized (the larger surface) and settling to 1 (the small
        // target). The cap keeps a pathological ratio from exploding.
        let startX = max(0.05, min(8, start.width / max(1, size.width)))
        let startY = max(0.05, min(8, start.height / max(1, size.totalHeight)))
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction) {
            surfaceScaleX = startX
            surfaceScaleY = startY
        }
        DispatchQueue.main.async {
            withAnimation(T.spring) {
                surfaceScaleX = 1
                surfaceScaleY = 1
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch snapshot.visual {
        case "idle_collapsed":
            Color.clear
        case "idle_peek":
            peekEars
        case "idle_pinned":
            pinnedPanel
        case "listening":
            if size.notchHeight > 0 { activeStrip } else { bars }
        case "danger_confirm":
            if size.notchHeight > 0 { dangerStrip } else { danger }
        case "text_input":
            TextInputView(prompt: snapshot.inputPrompt, prefill: snapshot.inputPrefill, emit: emit)
        default:
            if size.notchHeight > 0 { activeStrip } else { stateLabel }
        }
    }

    /// Hover peek content. With a physical notch, clock and battery sit as two
    /// glanceable "ears" flanking it (iPhone Dynamic Island idle style), a center
    /// gap the width of the hardware notch keeping both clear of it. WITHOUT a
    /// notch there is nothing to flank, so they group into one compact centered
    /// chip (clock · battery) — see visualSize's compactPeekWidth.
    @ViewBuilder
    private var peekEars: some View {
        Group {
            if size.notchWidth > 0 {
                HStack(spacing: 0) {
                    clockLabel
                    Spacer(minLength: size.notchWidth)
                    batteryLabel
                }
            } else {
                HStack(spacing: T.space2) {
                    clockLabel
                    if showsPeekDivider {
                        Circle()
                            .fill(T.ink3)
                            .frame(width: 2.5, height: 2.5)
                    }
                    batteryLabel
                }
            }
        }
        .padding(.horizontal, T.space4)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var showsPeekDivider: Bool {
        snapshot.showClock && !snapshot.clockTime.isEmpty && snapshot.batteryPercent != nil
    }

    @ViewBuilder
    private var clockLabel: some View {
        if snapshot.showClock, !snapshot.clockTime.isEmpty {
            Text(snapshot.clockTime)
                .font(T.body)
                .foregroundStyle(T.ink)
                .monospacedDigit()
                .lineLimit(1)
        }
    }

    @ViewBuilder
    private var batteryLabel: some View {
        if let pct = snapshot.batteryPercent {
            HStack(spacing: T.space1 - 1) {
                Image(systemName: batterySymbol(pct))
                    .font(.system(size: 12))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(batteryColor(pct))
                Text("\(pct)%")
                    .font(T.body)
                    .foregroundStyle(T.ink)
                    .monospacedDigit()
                    .lineLimit(1)
            }
        }
    }

    private var bars: some View {
        let bars = snapshot.micBars.isEmpty ? Array(repeating: CGFloat(0.08), count: 6) : snapshot.micBars
        return HStack(spacing: 8) {
            ForEach(Array(bars.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 3)
                    .fill(accent)
                    .frame(width: 6, height: max(3, value * max(1, size.contentHeight - 16)))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var stateLabel: some View {
        VStack(spacing: T.space1) {
            HStack(spacing: T.space2) {
                // Live activity indicator while the agent is working, so the
                // wait never looks frozen.
                if snapshot.state == "processing" || snapshot.state == "executing" {
                    ProgressView()
                        .controlSize(.small)
                        .tint(accent)
                } else {
                    Image(systemName: stateSymbol(snapshot.state))
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(accent)
                        .symbolRenderingMode(.hierarchical)
                }
                Text(snapshot.stateLabel)
                    .font(T.title)
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            if !snapshot.transcript.isEmpty {
                Text("\"\(snapshot.transcript)\"")
                    .font(T.caption)
                    .foregroundStyle(T.ink2)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, T.space4)
    }

    private var danger: some View {
        VStack(spacing: T.space2 + 2) {
            HStack(spacing: T.space1 + 2) {
                Image(systemName: stateSymbol("danger_confirm"))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(accent)
                Text(snapshot.stateLabel)
                    .font(T.title)
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            HStack(spacing: T.space3) {
                Button("실행") { emit("dangerAllow", [:]) }
                    .buttonStyle(CapsuleButtonStyle(prominent: true))
                    .tint(.red)
                    .keyboardShortcut(.defaultAction)
                Button("취소") { emit("dangerDeny", [:]) }
                    .buttonStyle(CapsuleButtonStyle())
                    .keyboardShortcut(.cancelAction)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 16)
    }

    // MARK: - Physical-notch strip layouts
    //
    // On a display WITH a hardware notch, hover + active states render as a
    // notch-height strip whose content flanks the notch as two "ears" (never
    // behind it), growing only left/right — see visualSize / notchStripVisuals.

    /// SF Symbol for the active strip's left ear. The user's examples map here:
    /// "..." (ellipsis) for listening, "!" (exclamationmark) for error; the two
    /// working states use a spinner instead (see activeStripIcon).
    private func stripSymbol(_ state: String) -> String {
        switch state {
        case "listening": return "ellipsis"
        case "success": return "checkmark"
        case "error": return "exclamationmark"
        default: return "circle.fill"
        }
    }

    @ViewBuilder
    private var activeStripIcon: some View {
        if snapshot.state == "processing" || snapshot.state == "executing" {
            ProgressView()
                .controlSize(.small)
                .tint(accent)
        } else {
            Image(systemName: stripSymbol(snapshot.state))
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(accent)
                .symbolRenderingMode(.hierarchical)
        }
    }

    /// Active-state strip: state icon on the left ear, status message on the
    /// right ear, both flanking the notch at exactly its height. When a command
    /// transcript is present the pill grows DOWNWARD to show it on a full-width
    /// row beneath the notch line — the one place text can appear without the
    /// hardware notch covering it. The accent keeps the per-state color.
    private var activeStrip: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                activeStripIcon
                Spacer(minLength: size.notchWidth)
                Text(snapshot.stateLabel)
                    .font(T.body)
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            .padding(.horizontal, T.space4)
            .frame(height: size.notchHeight)
            if !snapshot.transcript.isEmpty {
                Text("\"\(snapshot.transcript)\"")
                    .font(T.caption)
                    .foregroundStyle(T.ink2)
                    .lineLimit(1)
                    .padding(.horizontal, T.space4)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Danger confirm on a notched display: the warning icon on the left ear and
    /// the 실행 / 취소 buttons grouped on the right ear, flanking the notch in one
    /// notch-height row (no downward growth behind the island).
    private var dangerStrip: some View {
        HStack(spacing: 0) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(accent)
                .symbolRenderingMode(.hierarchical)
            Spacer(minLength: size.notchWidth)
            HStack(spacing: T.space2) {
                dangerStripButton("실행", tint: accent, allow: true)
                dangerStripButton("취소", tint: nil, allow: false)
            }
        }
        .padding(.horizontal, T.space4)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Compact capsule button for the danger strip. Emits from a tap gesture
    /// rather than a SwiftUI Button because the pill's window is never key
    /// outside the text-input path, and a Button's action does not fire on a
    /// non-key window (same reason the pinned panel's gear/chips use gestures).
    private func dangerStripButton(_ title: String, tint: Color?, allow: Bool) -> some View {
        Text(title)
            .font(T.font(11.5, .semibold))
            .foregroundStyle(tint == nil ? T.ink : Color.white)
            .padding(.horizontal, T.space3)
            .padding(.vertical, T.space1)
            .background(Capsule(style: .continuous).fill(tint ?? T.control))
            .contentShape(Capsule())
            .highPriorityGesture(TapGesture().onEnded {
                emit(allow ? "dangerAllow" : "dangerDeny", [:])
            })
    }

    private var artworkImage: NSImage? {
        guard !snapshot.mediaArtwork.isEmpty,
              let data = Data(base64Encoded: snapshot.mediaArtwork) else { return nil }
        return NSImage(data: data)
    }

    /// Small round transport button (prev/play-pause/next) — filled circle so
    /// it reads as tappable at this size, unlike a bare SF Symbol glyph.
    private func transportButton(_ symbol: String, _ event: String) -> some View {
        Button {
            emit(event, [:])
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.white)
                .frame(width: 27, height: 27)
                .background(Circle().fill(T.control))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var mediaCardContent: some View {
        VStack(alignment: .leading, spacing: T.space2) {
            HStack(alignment: .center, spacing: 10) {
                Group {
                    if let image = artworkImage {
                        Image(nsImage: image)
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: 40, height: 40)
                            .clipShape(RoundedRectangle(cornerRadius: T.rArt, style: .continuous))
                    } else {
                        iconBadge("music.note", .pink, size: 40)
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(snapshot.mediaTitle)
                        .font(T.title)
                        .foregroundStyle(T.ink)
                        .lineLimit(1)
                    Text(snapshot.mediaArtist)
                        .font(T.caption)
                        .foregroundStyle(T.ink2)
                        .lineLimit(1)
                }
                if snapshot.mediaPlaying {
                    EqualizerGlyph()
                }
                Spacer(minLength: 4)
                if !snapshot.mediaPlayerApp.isEmpty {
                    HStack(spacing: 6) {
                        transportButton("backward.fill", "mediaPrev")
                        transportButton(
                            snapshot.mediaPlaying ? "pause.fill" : "play.fill", "mediaPlayPause"
                        )
                        transportButton("forward.fill", "mediaNext")
                    }
                }
            }
            // Scrubber — only when we know the track length. Seeking emits
            // `mediaSeek`, which the Python side turns into `set player position`.
            if !snapshot.mediaPlayerApp.isEmpty && snapshot.mediaDuration > 0 {
                MediaSeekBar(
                    position: snapshot.mediaPosition,
                    duration: snapshot.mediaDuration,
                    playing: snapshot.mediaPlaying,
                    onSeek: { emit("mediaSeek", ["position": $0]) }
                )
            }
        }
    }

    /// Faint card container that groups a widget. A subtle top-lit gradient
    /// plus a 1px hairline gives each segment gentle dimensionality on the
    /// flat-black pill — distinct-but-unified panel segments.
    private func card<Content: View>(
        fillHeight: Bool = false,
        @ViewBuilder _ content: () -> Content
    ) -> some View {
        content()
            .padding(.horizontal, T.space3)
            .padding(.vertical, T.space2 + 2)
            .frame(
                maxWidth: .infinity,
                maxHeight: fillHeight ? .infinity : nil,
                alignment: .leading
            )
            .background(
                RoundedRectangle(cornerRadius: T.rCard, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [T.cardTop, T.cardBottom],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
            )
    }

    /// Command palette pinned to the panel's bottom: a Spotlight-style list of
    /// the user's most-used commands (tap to re-run) sitting directly above the
    /// always-on input field. One card groups the two so they read as a single
    /// "command bar" region.
    @ViewBuilder
    private var commandPaletteCard: some View {
        card {
            VStack(spacing: T.space2) {
                if !snapshot.commandSuggestions.isEmpty {
                    VStack(spacing: 1) {
                        ForEach(snapshot.commandSuggestions, id: \.self) { command in
                            suggestionRow(command)
                        }
                    }
                    Rectangle()
                        .fill(T.hairline)
                        .frame(height: 1)
                        .padding(.horizontal, -T.space2)
                }
                VStack(spacing: 6) {
                    commandInputBar
                    engineStatusLine
                }
            }
        }
    }

    /// Which engines will handle a command — a muted caption sitting with the
    /// command bar (STT/LLM/TTS + a green "running" dot). Low-priority status,
    /// so it reads as a footnote to the input rather than its own widget.
    @ViewBuilder
    private var engineStatusLine: some View {
        if !snapshot.providerSummary.isEmpty {
            HStack(spacing: T.space1 + 1) {
                Circle()
                    .fill(Color.green.opacity(0.85))
                    .frame(width: 5, height: 5)
                Text(snapshot.providerSummary)
                    .font(T.font(9.5, .medium))
                    .tracking(0.2)
                    .foregroundStyle(T.ink3)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, T.space1)
        }
    }

    /// One tappable command in the palette — leading category icon + the command
    /// text. Emits `commandSuggestion`, which the Python side runs through the
    /// agent under the command lock.
    private func suggestionRow(_ command: String) -> some View {
        let icon = suggestionIcon(command)
        return Button {
            emit("commandSuggestion", ["command": command])
        } label: {
            HStack(spacing: T.space2) {
                Image(systemName: icon.symbol)
                    .font(.system(size: 12, weight: .semibold))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(icon.tint)
                    .frame(width: 18)
                Text(command)
                    .font(T.body)
                    .foregroundStyle(T.ink)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: T.space1)
                Image(systemName: "arrow.turn.down.left")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(T.ink3)
            }
            .padding(.vertical, 6)
            .padding(.horizontal, T.space1)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    /// Always-on "type a command" field at the panel's bottom, beneath the
    /// command palette. Submitting emits `commandSubmit`, which follows the
    /// same locked agent path as a tapped suggestion.
    private var commandInputBar: some View {
        HStack(spacing: T.space2) {
            TextField("명령을 입력하세요", text: $commandDraft)
                .textFieldStyle(.plain)
                .font(T.body)
                .foregroundStyle(T.ink)
                .tint(Color(red: 0.40, green: 0.72, blue: 1.0))
                .lineLimit(1)
                .focused($commandFieldFocused)
                .onSubmit(submitTypedCommand)
                .onExitCommand { endCommandInput() }
                .simultaneousGesture(TapGesture().onEnded { beginCommandInput() })
            Spacer(minLength: 0)
            Button {
                submitTypedCommand()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(commandDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                     ? T.ink3 : Color(red: 0.40, green: 0.72, blue: 1.0))
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, T.space3)
        .padding(.vertical, T.space2)
        .background(
            RoundedRectangle(cornerRadius: T.rArt, style: .continuous)
                .fill(T.control)
        )
        .overlay(
            RoundedRectangle(cornerRadius: T.rArt, style: .continuous)
                .strokeBorder(commandFieldFocused ? Color(red: 0.40, green: 0.72, blue: 1.0).opacity(0.65)
                              : Color.clear, lineWidth: 1)
        )
    }

    private func beginCommandInput() {
        emit("inlineEditBegin", [:])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
            commandFieldFocused = true
        }
    }

    private func endCommandInput() {
        commandFieldFocused = false
        emit("inlineEditEnd", [:])
    }

    private func submitTypedCommand() {
        let command = commandDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !command.isEmpty else {
            endCommandInput()
            return
        }
        commandDraft = ""
        commandFieldFocused = false
        emit("commandSubmit", ["command": command])
        emit("inlineEditEnd", [:])
    }

    /// A small circular badge behind an SF Symbol — reads as a proper icon
    /// rather than a bare glyph, and the tinted background carries the
    /// per-widget color even before the eye reaches the label text.
    private func iconBadge(_ symbol: String, _ tint: Color, size: CGFloat = 26) -> some View {
        ZStack {
            Circle().fill(tint.opacity(0.18))
            Image(systemName: symbol)
                .font(.system(size: size * 0.44, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(tint)
        }
        .frame(width: size, height: size)
        // Rasterize glyph + circle as one unit so they stay centered together
        // on 1x displays (otherwise the glyph can pixel-snap ~1px off-center).
        .drawingGroup()
    }

    private var pinnedPanel: some View {
        VStack(spacing: T.space2 + 2) {
            pinnedHeader
                .hidden()
                .accessibilityHidden(true)
                // Extra breathing room below the header so the first content
                // card (now-playing) isn't crowded against the HeyDesk /
                // battery / gear row. Only widens this one gap, not every card.
                .padding(.bottom, 10)

            // Top strip: now-playing. The command input moved to the panel
            // bottom (see commandPaletteCard); the freed slot beside media is
            // reserved for a widget to be decided.
            if snapshot.showMedia {
                card { mediaCardContent }
                    .frame(maxWidth: .infinity)
            }

            // Time & schedule row: a tall analog clock (with the next event
            // beneath it) on the left, the month-grid calendar on the right,
            // both stretched to the same height.
            if snapshot.showClock {
                HStack(alignment: .top, spacing: T.space2 + 2) {
                    card(fillHeight: true) {
                        AnalogClockWidget(
                            time: snapshot.clockTime,
                            date: snapshot.clockDate,
                            nextTitle: snapshot.nextEventTitle,
                            nextTime: snapshot.nextEventTime
                        )
                    }
                    .frame(maxWidth: .infinity)
                    card {
                        CalendarWidget(
                            todos: snapshot.todos,
                            monthOffset: snapshot.calMonthOffset,
                            selectedDate: snapshot.calSelectedDate,
                            emit: emit
                        )
                    }
                        .frame(maxWidth: .infinity)
                }
                .fixedSize(horizontal: false, vertical: true)
            }

            if !snapshot.routines.isEmpty {
                card {
                    VStack(alignment: .leading, spacing: T.space2 - 2) {
                        HStack(spacing: T.space1 + 1) {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.yellow)
                            Text("단축어")
                                .font(T.label)
                                .tracking(0.4)
                                .foregroundStyle(T.ink2)
                        }
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: T.space2) {
                                ForEach(snapshot.routines, id: \.self) { routine in
                                    routineChip(routine)
                                }
                            }
                        }
                    }
                }
            }

            // Command palette + input (with the engine-status caption). Uses
            // the same T.space2 + 2 gap as every other card — no expanding
            // spacer above it, so the spacing stays consistent panel-wide.
            commandPaletteCard

            HStack(spacing: T.space1) {
                Image(systemName: "chevron.up")
                    .font(.system(size: 8, weight: .bold))
                Text("다시 클릭하면 접힙니다")
                    .font(T.font(9.5, .medium))
                    .tracking(0.3)
            }
            .foregroundStyle(T.ink3)
            .padding(.top, T.space1 + 2)
        }
        .padding(.horizontal, T.space4)
        .padding(.top, T.space3)
        // Roomier bottom margin so the collapse hint isn't crowded against the
        // panel's rounded bottom edge.
        .padding(.bottom, T.space4 + T.space1)
        // Top-anchor the stack so every inter-card gap is exactly the VStack
        // spacing; any leftover height (panel taller than content) collects at
        // the very bottom instead of stretching a gap between cards.
        .frame(maxHeight: .infinity, alignment: .top)
    }

    // The 7 symmetric bars from waveform.svg (viewBox 640×560), drawn as a
    // Shape so it inherits the header's foregroundStyle just like an SF Symbol.
    private struct WaveformShape: Shape {
        func path(in rect: CGRect) -> Path {
            let bars: [(x: CGFloat, y: CGFloat, h: CGFloat)] = [
                (0, 115, 330), (92, 14, 532), (184, 153, 254), (276, 226, 108),
                (368, 153, 254), (460, 14, 532), (552, 115, 330),
            ]
            let vbW: CGFloat = 640, vbH: CGFloat = 560
            let sx = rect.width / vbW, sy = rect.height / vbH
            var p = Path()
            for b in bars {
                let r = CGRect(x: rect.minX + b.x * sx, y: rect.minY + b.y * sy,
                               width: 44 * sx, height: b.h * sy)
                p.addRoundedRect(in: r, cornerSize: CGSize(width: 22 * sx, height: 22 * sx))
            }
            return p
        }
    }

    private var pinnedHeader: some View {
        HStack {
            HStack(spacing: T.space1 + 1) {
                WaveformShape()
                    .frame(width: 13, height: 11)
                    .foregroundStyle(T.ink)
                Text("HeyDesk")
                    .font(T.label)
                    .tracking(0.4)
                    .foregroundStyle(T.ink2)
            }
            Spacer()
            if let pct = snapshot.batteryPercent {
                HStack(spacing: T.space1 - 1) {
                    Image(systemName: batterySymbol(pct))
                        .font(.system(size: 11))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(batteryColor(pct))
                    Text("\(pct)%")
                        .font(T.caption)
                        .foregroundStyle(T.ink2)
                        .monospacedDigit()
                }
            }
            // A SwiftUI Button's action does not fire while this panel's
            // window is non-key (only the text-input path makes it key), so
            // emit directly from a tap gesture like the rest of the HUD.
            Image(systemName: "gearshape.fill")
                .font(.system(size: 12))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(T.ink2)
                .contentShape(Rectangle())
                .highPriorityGesture(
                    TapGesture().onEnded { emit("openSettings", [:]) }
                )
        }
    }

    /// One saved routine as a tappable capsule chip in the quick-launch row.
    private func routineChip(_ name: String) -> some View {
        Button {
            emit("runRoutine", ["name": name])
        } label: {
            HStack(spacing: T.space1 + 1) {
                Image(systemName: "play.fill")
                    .font(.system(size: 8, weight: .semibold))
                Text(name)
                    .font(T.body)
                    .lineLimit(1)
            }
            .padding(.horizontal, T.space3)
            .padding(.vertical, T.space1 + 2)
            .background(Capsule(style: .continuous).fill(T.control))
        }
        .buttonStyle(.plain)
    }

    private func batteryColor(_ pct: Int) -> Color {
        snapshot.batteryCharging ? .green : (pct <= 20 ? .red : .secondary)
    }

    private func batterySymbol(_ pct: Int) -> String {
        if snapshot.batteryCharging { return "bolt.fill" }
        switch pct {
        case ..<15: return "battery.0"
        case ..<40: return "battery.25"
        case ..<65: return "battery.50"
        case ..<90: return "battery.75"
        default: return "battery.100"
        }
    }
}

private final class HUDController {
    private let emitter = EventEmitter()
    private var snapshot = HUDSnapshot()
    private var windows: [String: NSWindow] = [:]
    // Reusing the hosting view (instead of replacing contentView on every
    // render) is required for hover to work at all: recreating it tears down
    // and remounts the view's NSTrackingArea every call, which AppKit reports
    // as a fresh mouseExited/mouseEntered pair even though the pointer never
    // moved — observed as hoverEnter/hoverExit firing in an infinite ~40ms
    // loop that never survives long enough for the dwell timer to fire.
    private var hostingViews: [String: FirstMouseHostingView<HUDView>] = [:]
    private var lastVisual = ""
    private var lastState = ""
    // Tracks whether the pinned panel held keyboard focus on the previous
    // render, so a closing inline todo field can hand focus back to the user's
    // app exactly once.
    private var lastInlineKeyboard = false
    // A second, independent source of the same oscillation: while the
    // window's frame is mid-animation (see the spring resize in render()),
    // AppKit's hit-testing for the hosting view's NSTrackingArea is
    // unreliable — it reports spurious mouseExited/mouseEntered pairs even
    // though the real cursor never moved. There is no way to distinguish
    // those from a genuine mouse-leave using the events alone, so hover
    // enter/exit is suppressed for the animation's duration after any frame
    // change; genuine clicks are never touched by this.
    private var suppressHoverUntil: Date = .distantPast
    private var lastHoverInside: Bool? = nil
    private var hoverMonitors: [Any] = []
    private let frameAnimationDuration: TimeInterval = 0.4
    private let hoverTopSlop: CGFloat = 12
    private let hoverSideSlop: CGFloat = 6
    private var surfaceAnimationID = 0

    /// Subtle NotchNook-style interaction sounds on meaningful transitions.
    private func playTransitionSound() {
        var name: String?
        if snapshot.visual == "idle_pinned" && lastVisual != "idle_pinned" {
            name = "Pop"
        } else if snapshot.state == "success" && lastState != "success" {
            name = "Glass"
        } else if snapshot.state == "error" && lastState != "error" {
            name = "Basso"
        } else if snapshot.state == "listening" && lastState != "listening" {
            name = "Tink"
        }
        if snapshot.interactionSounds, let name, let sound = NSSound(named: name) {
            sound.volume = 0.3
            sound.play()
        }
        lastVisual = snapshot.visual
        lastState = snapshot.state
    }

    func handle(_ line: String) {
        guard let data = line.data(using: .utf8),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = raw["type"] as? String else {
            emitter.log("[SwiftHUD] invalid command")
            return
        }

        switch type {
        case "render":
            snapshot = HUDSnapshot(raw)
            render()
        case "hide":
            hide()
        case "quit":
            hide()
            NSApp.terminate(nil)
        default:
            emitter.log("[SwiftHUD] unknown command: \(type)")
        }
    }

    private func render() {
        guard snapshot.visible else {
            hide()
            return
        }
        installHoverMonitors()

        // A "surface morph" swells the pill out of / retracts it into the notch
        // with a top-anchored scale, so growth and shrink read as one motion run
        // forward or backward — always from / into the notch, never resizing in
        // from a side. It plays between two COMPATIBLE surfaces: the idle ladder
        // (collapsed → peek → pinned), or the compact notch-strip surfaces
        // (collapsed + the active states listening…error + danger). collapsed is
        // in both, so idle grows out to a panel OR out to an active strip; the
        // active states now morph just like the idle ladder always has. Grow vs
        // shrink, and whether a morph plays at all, are decided per-window from
        // the actual old/new size (see the loop) so a same-size re-render — e.g.
        // a mic-level tick during listening — never restarts the animation.
        let shouldMorph = isMorphPair(from: lastVisual, to: snapshot.visual)
        var animationBumped = false

        let activeKeys = Set(NSScreen.screens.map(screenKey))
        for key in windows.keys where !activeKeys.contains(key) {
            windows[key]?.orderOut(nil)
            windows.removeValue(forKey: key)
            hostingViews.removeValue(forKey: key)
        }

        for screen in NSScreen.screens {
            let key = screenKey(screen)
            let size = visualSize(for: snapshot, screen: screen)
            let frame = NSRect(
                x: screen.frame.midX - size.width / 2,
                y: screen.frame.maxY - size.totalHeight,
                width: size.width,
                height: size.totalHeight
            )
            let isNewWindow = windows[key] == nil
            let window = windows[key] ?? makeWindow(frame: frame)
            windows[key] = window
            let needsResize = !rectNearlyEqual(window.frame, frame)
            // A morph plays only on a real resize of an existing window between
            // two compatible surfaces (a brand-new window has nothing to morph
            // from). Bump the shared animation id at most once per render, and
            // only when a morph will actually play, so same-size re-renders don't
            // restart an in-flight scale.
            let morph = shouldMorph && !isNewWindow && needsResize
            if morph && !animationBumped {
                surfaceAnimationID += 1
                animationBumped = true
            }
            // Scale between the surface on screen right now (the window's current
            // size) and the new one; capture it before the frame is touched.
            let surfaceStartSize: CGSize? = morph ? window.frame.size : nil
            // Grow vs shrink straight from the size change (area): a bigger
            // target grows out of the notch, a smaller one retracts back into it.
            let grows = morph &&
                frame.width * frame.height >= window.frame.width * window.frame.height
            let shrinks = morph && !grows
            if needsResize {
                if grows {
                    // Grow: jump to the bigger target now; the top-anchored
                    // scale carries the growth out of the notch.
                    suppressHoverUntil = Date().addingTimeInterval(frameAnimationDuration + 0.05)
                    window.setFrame(frame, display: true)
                    DispatchQueue.main.asyncAfter(deadline: .now() + frameAnimationDuration) { [weak self] in
                        self?.reconcileHover(force: true, confirmInside: true)
                    }
                } else if shrinks {
                    // Shrink: keep the window at its current (larger) size while
                    // the pill scales down inside it — a smaller window would
                    // clip the still-large pill and the retract would never be
                    // seen. Collapse the window to the small target only once the
                    // scale has settled, then re-render so the window (and its
                    // hover area) matches the pill exactly.
                    let settleDelay = frameAnimationDuration + 0.12
                    suppressHoverUntil = Date().addingTimeInterval(settleDelay + 0.05)
                    // If another render moves us to a different visual before the
                    // scale settles (e.g. a quick re-click or a state change),
                    // that render already owns the window — skip this now-stale
                    // collapse so it can't yank the window to the wrong size.
                    let settleVisual = snapshot.visual
                    let settleKey = key
                    DispatchQueue.main.asyncAfter(deadline: .now() + settleDelay) { [weak self, weak window] in
                        guard let self, let window, self.snapshot.visual == settleVisual else { return }
                        window.setFrame(frame, display: true)
                        self.settleShrunkSurface(key: settleKey)
                        self.reconcileHover(force: true, confirmInside: false)
                    }
                } else {
                    // A slight overshoot easing reads as a soft spring rather
                    // than AppKit's flat linear-ish default — the difference
                    // between a mechanical resize and a "grows out of the
                    // notch" feel.
                    suppressHoverUntil = Date().addingTimeInterval(frameAnimationDuration + 0.05)
                    NSAnimationContext.runAnimationGroup({ ctx in
                        ctx.duration = self.frameAnimationDuration
                        ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.32, 1.2, 0.4, 1.0)
                        window.animator().setFrame(frame, display: true)
                    }, completionHandler: { [weak self] in
                        self?.settleFrameAnimation(for: window)
                    })
                }
            }
            // During a shrink the window is briefly larger than the pill, so the
            // pill is centered at the window's top inside that box; otherwise the
            // box equals the pill and it's a no-op. Read AFTER the frame work
            // above so it reflects the grow-snap / shrink-hold.
            let surfaceContainerSize: CGSize? =
                surfaceStartSize != nil ? window.frame.size : nil
            installHUDView(
                forKey: key,
                into: window,
                size: size,
                surfaceStartSize: surfaceStartSize,
                surfaceContainerSize: surfaceContainerSize
            )
            if isNewWindow || !window.isVisible {
                window.orderFrontRegardless()
            }
        }

        // The text field must own keyboard focus while an input is open — the
        // full-screen text_input visual, or an inline todo add/edit field in the
        // pinned panel (keyboardActive). When an inline field closes, hand focus
        // back to whatever app the user was in before.
        let wantsInlineKeyboard = snapshot.visual == "idle_pinned" && snapshot.keyboardActive
        if snapshot.visual == "text_input" || wantsInlineKeyboard {
            NSApp.activate(ignoringOtherApps: true)
            let mainKey = NSScreen.main.map(screenKey)
            if let key = mainKey, let window = windows[key] {
                window.makeKeyAndOrderFront(nil)
            } else {
                windows.values.first?.makeKeyAndOrderFront(nil)
            }
        } else if lastInlineKeyboard {
            NSApp.deactivate()
        }
        lastInlineKeyboard = wantsInlineKeyboard

        playTransitionSound()
    }

    /// Build the SwiftUI pill for one screen's window and mount it (reusing the
    /// existing hosting view so its NSTrackingArea survives — see the note on
    /// `hostingViews`). Shared by the main render loop and the per-window shrink
    /// settle so both mount identical views.
    private func installHUDView(
        forKey key: String,
        into window: NSWindow,
        size: VisualSize,
        surfaceStartSize: CGSize?,
        surfaceContainerSize: CGSize?
    ) {
        let hudView = HUDView(
            snapshot: snapshot,
            size: size,
            surfaceStartSize: surfaceStartSize,
            surfaceContainerSize: surfaceContainerSize,
            surfaceAnimationID: surfaceAnimationID,
            emit: makeEmitHandler()
        )
        if let hostingView = hostingViews[key] {
            hostingView.rootView = hudView
        } else {
            let hostingView = FirstMouseHostingView(rootView: hudView)
            hostingViews[key] = hostingView
            window.contentView = hostingView
        }
    }

    private func makeEmitHandler() -> (String, [String: Any]) -> Void {
        return { [weak self] event, extra in
            guard let self else { return }
            let isHoverEdge = (event == "hoverEnter" || event == "hoverExit")
            if isHoverEdge && Date() < self.suppressHoverUntil {
                return   // animation-artifact hover event — not a real cursor move
            }
            if event == "hoverEnter" {
                self.lastHoverInside = true
            } else if event == "hoverExit" {
                self.lastHoverInside = false
            }
            self.emitter.emit(event, extra)
        }
    }

    /// After a per-window shrink hold settles, drop the oversized container so
    /// the pill sits in its own (now small) frame. Rebuilds ONLY this window.
    ///
    /// It must NOT re-enter the global `render()`: on a multi-display setup each
    /// screen holds its own window and settles on its own delayed closure, so
    /// when the first screen's settle fires the sibling window on another screen
    /// is still mid-shrink. `render()` would re-loop over that sibling — but
    /// `lastVisual` has already advanced to the new visual, so the sibling no
    /// longer classifies as a shrink and falls through to the overshoot resize
    /// branch, springing that notch left-right. Touching one window avoids the
    /// cross-talk; each sibling settles cleanly on its own closure.
    private func settleShrunkSurface(key: String) {
        guard snapshot.visible,
              let window = windows[key],
              let screen = NSScreen.screens.first(where: { screenKey($0) == key }) else { return }
        let size = visualSize(for: snapshot, screen: screen)
        installHUDView(
            forKey: key,
            into: window,
            size: size,
            surfaceStartSize: nil,
            surfaceContainerSize: nil
        )
    }

    private func hide() {
        for window in windows.values {
            window.orderOut(nil)
        }
        removeHoverMonitors()
        lastHoverInside = nil
    }

    private func settleFrameAnimation(for window: NSWindow) {
        // Reconcile hover edges that may have been suppressed during the frame
        // animation. (The window has no shadow, so there is no shadow ghost to
        // re-derive here anymore.)
        reconcileHover(force: true, confirmInside: true)
    }

    /// The idle size ladder — collapsed → peek → pinned — whose members morph
    /// into one another (a hover peek, a click to the big panel, and back).
    private func isIdleLadder(_ visual: String) -> Bool {
        visual == "idle_collapsed" || visual == "idle_peek" || visual == "idle_pinned"
    }

    /// The compact notch-strip surfaces: the collapsed notch plus every active
    /// state (listening…error) and the danger prompt. These sit at the notch and
    /// grow only left/right (+ down for a transcript), so they morph among
    /// themselves and to/from the collapsed notch with the same scale-out.
    private func isNotchStripSurface(_ visual: String) -> Bool {
        switch visual {
        case "idle_collapsed", "listening", "processing", "executing",
             "success", "error", "danger_confirm":
            return true
        default:
            return false
        }
    }

    /// True when a top-anchored scale morph should play between `from` and `to`:
    /// both on the idle ladder, or both compact notch-strip surfaces. collapsed
    /// belongs to both groups, so it morphs out to a panel OR out to an active
    /// strip. Any idle surface can also collapse directly into an active strip
    /// when a wake-word activation arrives while the large panel is open.
    /// text_input (the full keyboard panel) is in neither and plain-resizes.
    private func isMorphPair(from: String, to: String) -> Bool {
        (isIdleLadder(from) && isIdleLadder(to))
            || (isNotchStripSurface(from) && isNotchStripSurface(to))
            || (isIdleLadder(from) && isNotchStripSurface(to))
    }

    private func installHoverMonitors() {
        guard hoverMonitors.isEmpty else { return }
        let mask: NSEvent.EventTypeMask = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged]
        if let local = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { [weak self] event in
            self?.reconcileHover()
            return event
        }) {
            hoverMonitors.append(local)
        }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: { [weak self] _ in
            self?.reconcileHover()
        }) {
            hoverMonitors.append(global)
        }
    }

    private func removeHoverMonitors() {
        for monitor in hoverMonitors {
            NSEvent.removeMonitor(monitor)
        }
        hoverMonitors.removeAll()
    }

    private func reconcileHover(force: Bool = false, confirmInside: Bool = false) {
        guard snapshot.visible else { return }
        if !force && Date() < suppressHoverUntil {
            return
        }
        let cursor = NSEvent.mouseLocation
        let inside = windows.values.contains { window in
            window.isVisible && self.hoverFrame(for: window).contains(cursor)
        }
        guard lastHoverInside != inside else { return }
        lastHoverInside = inside
        if inside {
            emitter.emit(confirmInside ? "hoverConfirm" : "hoverEnter", [:])
        } else {
            emitter.emit("hoverExit", [:])
        }
    }

    private func hoverFrame(for window: NSWindow) -> NSRect {
        var frame = window.frame
        frame.origin.x -= hoverSideSlop
        frame.size.width += hoverSideSlop * 2
        frame.size.height += hoverTopSlop
        return frame
    }

    private func makeWindow(frame: NSRect) -> NSWindow {
        let window = KeyableWindow(
            contentRect: frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.statusWindow)) + 1)
        window.isOpaque = false
        window.backgroundColor = .clear
        // No window shadow: the non-opaque window's drop shadow rendered as a
        // soft grey halo hugging the pill's rounded edge, which read as a grey
        // border around the surface in every state. The pill is a flat black
        // shape with no outline of any kind.
        window.hasShadow = false
        window.ignoresMouseEvents = false
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .ignoresCycle,
            .fullScreenAuxiliary,
        ]
        window.isReleasedWhenClosed = false
        return window
    }

    private func screenKey(_ screen: NSScreen) -> String {
        if let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
            return number.stringValue
        }
        return NSStringFromRect(screen.frame)
    }
}

private final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}

/// Register the bundled Pretendard variable font so `Font.custom` resolves it
/// even when the user hasn't installed Pretendard system-wide. The .ttf path is
/// handed down by the Python launcher (VOICEDESK_HUD_FONT); we also probe the
/// standard user Fonts dir for local dev runs. Silent no-op on failure — the
/// type tokens then fall back to the system font and the HUD still renders.
private func registerPretendard() {
    var candidates: [String] = []
    if let p = ProcessInfo.processInfo.environment["VOICEDESK_HUD_FONT"], !p.isEmpty {
        candidates.append(p)
    }
    candidates.append(NSString(string: "~/Library/Fonts/PretendardVariable.ttf").expandingTildeInPath)
    for path in candidates where FileManager.default.fileExists(atPath: path) {
        let url = URL(fileURLWithPath: path) as CFURL
        CTFontManagerRegisterFontsForURL(url, .process, nil)
        break
    }
}

registerPretendard()

private let controller = HUDController()
private let app = NSApplication.shared
private let delegate = AppDelegate()
app.delegate = delegate

DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine(strippingNewline: true) {
        DispatchQueue.main.async {
            controller.handle(line)
        }
    }
    DispatchQueue.main.async {
        controller.handle("{\"type\":\"quit\"}")
    }
}

app.run()
withExtendedLifetime(delegate) {}
