"""Single page processing.
"""

import os
import cv2
import numpy as np
from IPython.display import HTML, display

from .lib import (
    addBox,
    applyHRules,
    cluster,
    connected,
    getBlocks,
    getHistograms,
    getStretches,
    getStripes,
    grayInterBlocks,
    parseBands,
    parseMarks,
    parseStages,
    removeSkewStripes,
    showImage,
    splitext,
    storeCleanInfo,
)
from .ocr import OCR


class Page:
    def __init__(self, engine, f, batch=False, boxed=True):
        """All processing steps for a single page.

        Parameters
        ----------
        engine: object
            The `pipeline.book.Book` object
        f: string
            The file name of the scanned page with extension, without directory
        batch: boolean, optional `False`
            Whether to run in batch mode.
            In batch mode everything is geared to the final output.
            Less intermediate results are computed and stored.
            Less feedback happens on the console.
        boxed: boolean, optional `True`
            If in batch mode, produce also images that display the cleaned marks
            in boxes.
        """

        self.engine = engine
        C = engine.C
        tm = engine.tm
        error = tm.error
        self.file = f
        (self.bare, self.ext) = splitext(f, withDot=False)
        self.empty = True
        self.batch = batch
        self.boxed = boxed
        self.stages = {}
        self.bands = {}

        inDir = C.inDir
        path = f"{inDir}/{f}"
        if not batch and not os.path.exists(path):
            error(f"Page file not found: {path}")
            return

        self.empty = False
        orig = cv2.imread(path)

        self.stages = {"orig": orig}

    def show(self, stage=None, band=None, mark=None, **displayParams):
        """Displays processing stages of an page.

        See `pipeline.parameters.STAGES`.

        Parameters
        ----------
        stage: string | iterable, optional `None`
            If no stage is passed, all stages are shown as thumbnails.
            Otherwise, the indicated stages are shown.
            If a string, it may be a comma-separated list of stage names.
            Otherwise it is an iterable of stage names.
        band: string | iterable, optional `None`
            If no band is passed, no bands are indicated.
            Otherwise, the indicated bands are shown.
            If a string, it may be a comma-separated list of band names.
            Otherwise it is an iterable of band names.
        mark: string | iterable, optional `None`
            If `None` is passed, no marks are shown.
            If `""` is passed, all marks on the selected bands are shown.
            Otherwise, the indicated mark boxes are shown, irrespective
            of their bands:
            If given as a string, it may be a comma-separated list of mark names.
            Otherwise it is an iterable of mark names.
            This information will be taken from the result of the `markData` stage.
        display: dict, optional
            A set of display parameters, such as `width`, `height`
            (anything accepted by `IPython.display.Image`).

        Notes
        -----
        The mark option works for the "boxed" stage:
        All marks not specified in the mark parameter will not be shown.

        But this option also works for all other image stages: the marks
        will be displayed on a fresh copy of that stage.

        When used for a grayscale stage, the color of the mark boxes is lost.
        """

        engine = self.engine
        tm = engine.tm
        error = tm.error
        C = engine.C

        stages = self.stages
        bands = self.bands
        marks = engine.marks

        doBands = () if band is None else parseBands(band, set(bands), error)
        doBandSet = set(doBands)
        bandRep = f" with bands {', '.join(doBands)}" if doBands else ""

        doMarks = (
            set() if mark is None else parseMarks(mark, marks, set(doBands), error)
        )
        markRep = f" with marks {', '.join(sorted(doMarks))}" if doMarks else ""

        for s in parseStages(stage, set(stages), C.stageOrder, error):
            stageData = stages[s]

            display(HTML(f"<div>{s}{bandRep}{markRep}</div>"))

            (stageType, stageExt) = C.stages[s]
            if stageType == "data":
                self._serial(s, stageData, stageExt)
            else:
                img = stageData
                if doBands or mark is not None:
                    img = (
                        stages["demarginedC"]
                        if s == "boxed" and mark is not None
                        else stageData
                    ).copy()
                    imW = img.shape[1]
                    for band in doBands:
                        bandInfo = bands[band]
                        uppers = bandInfo["uppers"]
                        lowers = bandInfo["lowers"]
                        bColor = bandInfo["color"]
                        for (upper, lower) in zip(uppers, lowers):
                            cv2.rectangle(
                                img, (10, upper), (imW - 10, lower), bColor, 2
                            )
                            cv2.rectangle(img, (0, upper), (10, lower), bColor, -1)
                            cv2.rectangle(
                                img, (imW - 10, upper), (imW, lower), bColor, -1
                            )
                    markData = stages["markData"]
                    markLegend = {}
                    for (band, bandMarks) in markData.items():
                        if doBands and band not in doBandSet:
                            continue
                        for ((seq, mark), hits) in bandMarks.items():
                            if mark not in doMarks:
                                continue
                            markKey = f"{'' if band == 'main' else band[0]}{seq}"
                            markValue = (band, mark, len(hits))
                            markLegend[markKey] = markValue
                            for (
                                kept,
                                value,
                                connDegree,
                                connectBorder,
                                top,
                                bottom,
                                left,
                                right,
                            ) in hits:
                                addBox(
                                    C,
                                    img,
                                    top,
                                    bottom,
                                    left,
                                    right,
                                    kept,
                                    band,
                                    seq,
                                    connDegree,
                                )

                    if markLegend:
                        html = []
                        html.append(
                            "<details open><summary>Mark legend</summary><table>"
                        )
                        html.append(
                            "<tr><th>acro</th><th>band</th>"
                            "<th>mark</th><th>hits</th></tr>"
                        )
                        for (k, (b, m, n)) in sorted(markLegend.items()):
                            html.append(
                                f"<tr><td>{k}</td><td>{b}</td>"
                                f"<td>{m}</td><td>{n}</td></tr>"
                            )
                        html.append("</table></details>")
                        display(HTML("".join(html)))
                showImage(img, **displayParams)

    def write(self, stage=None):
        """Writes processing stages of an page to disk.

        Parameters
        ----------
        stage: string | iterable, optional `None`
            If no stage is passed, all stages are shown as thumbnails.
            Otherwise, the indicated stages are shown.
            If a string, it may be a comma-separated list of stage names.
            Otherwise it is an iterable of stage names.

        Returns
        -------
        None
            The stages are written into the `inter` subdirectory,
            with the name of the stage appended to the file name.
        """

        engine = self.engine
        tm = engine.tm
        error = tm.error
        C = engine.C
        interDir = C.interDir

        bare = self.bare
        ext = self.ext
        stages = self.stages

        for s in parseStages(stage, set(C.stages), C.stageOrder, error):
            if s not in stages:
                continue
            stageData = stages[s]
            (stageType, stageExt) = C.stages[s]
            path = f"{interDir}/{bare}-{s}.{stageExt or ext}"
            if stageType == "data":
                with open(path, "w") as f:
                    self._serial(s, stageData, stageExt, f)
            else:
                cv2.imwrite(path, stageData)

    def _serial(self, stage, data, extension, handle=None):
        """serializes data in accordance with file type.

        Parameters
        ----------
        data:
            The data to serialize. The type of data must be compatible with
            the *extension*.
        extension: string
            The file type according to which the data must be serialized.
        handle: string, optional `None`
            If `None`, output is prepared for display in a Jupter notebook,
            else it is a file handle and the data is serialized
            in the canonical way and written to that file.

        Returns
        -------
        string
            The serialized data.
            If the extension does not match a recognized file type,
            the Python `repr` of the data is returned.

        Notes
        -----
        The following data type/extension combinations are supported:

        extension | data type
        --- | ---
        tsv | tuple/list of tuple/list
        """

        engine = self.engine
        tm = engine.tm
        info = tm.info

        if handle:
            if stage == "markData":
                data = storeCleanInfo(data)
            handle.write(
                "".join("\t".join(str(column) for column in row) + "\n" for row in data)
                if extension == "tsv"
                else repr(data)
            )
        else:
            if stage == "markData":
                self._showCleanInfo()
            else:
                info(data, tm=False)

    def _normalize(self):
        """Normalizes a page.

        It produces a stage that is unskewed: *rotated* and blurred.
        The same rotation will be applied to the original scan,
        resulting in stage *normalized*.

        Unskewing is needed otherwise the footnote line will not be found.
        """

        if self.empty:
            return

        engine = self.engine
        C = engine.C

        batch = self.batch
        boxed = self.boxed
        stages = self.stages
        orig = stages["orig"]

        removeSkewStripes(orig, C.skewBorder, C.whiteRGB)
        gray = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)
        stages["gray"] = gray

        blurred = cv2.GaussianBlur(gray, (C.blurX, C.blurY), 0, 0)

        (th, threshed) = cv2.threshold(
            blurred, 127, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
        )
        pts = cv2.findNonZero(threshed)
        ret = cv2.minAreaRect(pts)

        (cx, cy), (rw, rh), ang = ret
        if rw > rh:
            rw, rh = rh, rw
            ang += 90

        M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)

        rotated = cv2.warpAffine(threshed, M, (threshed.shape[1], threshed.shape[0]))
        removeSkewStripes(rotated, C.skewBorder, C.blackRGB)
        normalized = cv2.warpAffine(gray, M, (gray.shape[1], gray.shape[0]))
        removeSkewStripes(normalized, C.skewBorder, C.whiteGRS)

        if not batch or boxed:
            normalizedC = cv2.warpAffine(orig, M, (orig.shape[1], orig.shape[0]))
            removeSkewStripes(normalizedC, C.skewBorder, C.whiteRGB)

        stages["rotated"] = rotated
        stages["normalized"] = normalized
        stages["normalizedC"] = normalizedC

    def _layout(self):
        """Divide the page into stripes and the stripes into columns.

        We detect vertical strokes as columns separators and horizontal strokes
        as separators to split off top and bottom material.

        A page may or may not be partially divided into columns.
        Where there is a vertical stroke, we define a stripe: the
        horizontal band that contains the vertical stroke tightly and extends to
        the full with of the page.

        Between the stripes corresponding to column separators we have stripes that
        are not split into columns.

        The stripes will be numbered from top to bottom, starting at 1.

        If a stripe is not split, it defines a roi (region of interest) with
        label `(i, '')`.

        If it is split, it defines blocks with labels `(i, 'r')` and `(i, 'l')`.

        Every horizontal stripe will be examined. W e have to determine whether
        it is a top separator or a bottom separator.
        As a rule of thumb: horizontal stripes in the top stripe are top-separators,
        all other horizontal stripes are bottom separators.

        If there are multiple horizontal strokes in a roi, the most aggressive
        one will be taken, i.e. the one that causes the most matarial to be discarded.

        All further operations will take place on these blocks (and not on the
        page as a whole).

        The result of this stage is, besides the blocks, an image of the page
        with the blocks marked and labelled.
        """

        batch = self.batch
        boxed = self.boxed
        engine = self.engine
        C = engine.C
        tm = engine.tm
        indent = tm.indent
        info = tm.info

        stages = self.stages
        layout = stages["normalizedC"].copy()
        stages["layout"] = layout

        indent(level=3)
        stretchesH = getStretches(C, info, stages, True)
        stretchesV = getStretches(C, info, stages, False)
        stripes = getStripes(stages, stretchesV)
        blocks = getBlocks(C, stages, stripes, batch)
        self.blocks = blocks
        applyHRules(C, stages, stretchesH, stripes, blocks, batch, boxed)
        emptyBlocks = getHistograms(C, stages, blocks, batch, boxed)
        grayInterBlocks(C, stages, blocks, emptyBlocks)

    def _clean(self, mark=None, block=None, line=None, showKept=False):
        """Remove marks from the page.

        The blocks of the page are cleaned of marks.

        New stages of the page are added:

        *   *clean* all targeted marks removed
        *   *cleanh* all targeted marks highlighted in light gray
        *   *boxed* all targeted marks boxed in light gray
        *   *markData* information about each detected mark.

        Parameters
        ----------
        mark: iterable of tuples (band, mark, [params]), optional `None`
            If `None`, all marks that are presented in the book
            directory are used.
            Otherwise, a series of marks is specified together with the band
            where this mark is searched in. Optionally you can also
            put parameters in the tuple: the accuracy and the connectBorder.
        block: (integer, string), optional `None`
            Block identifier. If specified, only this block will be cleaned.
            If absent, cleans all blocks.
        line: integer, optional `None`
            Line number specifying the line numbers to clean.
            In all specified blocks, only the line with this number will be cleaned.
            If absent, cleans all lines in the specified blocks.
        showKept: boolean, optional `False`
            Whether to show the mark candidates that are kept.
            If False, kept marks do not show up as green boxes,
            and they do not contribute to the markData layer.
        """

        if self.empty:
            return

        engine = self.engine
        tm = engine.tm
        indent = tm.indent
        info = tm.info
        error = tm.error
        warning = tm.warning
        C = engine.C

        marks = engine.marks
        batch = self.batch
        boxed = self.boxed

        markParams = C.markParams
        markParamSet = set(markParams.values())
        boxBorder = C.boxBorder

        connectBorder = C.connectBorder
        threshold = C.connectThreshold
        maxHits = C.maxHits
        color = dict(clean=C.cleanRGB, cleanh=C.cleanhRGB,)

        if mark is None:
            searchMarks = {subdir: markItems for (subdir, markItems) in marks.items()}
        else:
            searchMarks = {}
            for item in mark:
                (band, name) = item[0:2]
                if band not in marks or name not in marks[band]:
                    error(f"No such mark: {band}/{mark}")
                    continue
                params = item[2] if len(item) > 2 else {}
                for (k, v) in params.items():
                    if k not in markParamSet:
                        error(f"Unknown parameter `{k}` = `{v}`")
                configuredMark = marks[band][name]
                seq = configuredMark['seq']
                searchMarks.setdefault(band, {})[name] = dict(
                    seq=seq,
                    gray=configuredMark["gray"]
                )
                for k in markParams.values():
                    searchMarks[band][name][k] = params.get(k, configuredMark[k])

        stages = self.stages
        demargined = stages.get("demargined", stages["gray"])
        if batch:
            resultStages = ("clean", "boxed") if boxed else ("clean",)
            if boxed:
                demarginedC = stages.get("demarginedC", stages["orig"])
        else:
            demarginedC = stages.get("demarginedC", stages["orig"])
            resultStages = ("clean", "cleanh", "boxed")
        for stage in resultStages:
            stages[stage] = (demarginedC if stage == "boxed" else demargined).copy()

        tasks = [
            (
                stage,
                stages[stage],
                None if stage == "boxed" else color[stage],
                boxBorder if stage == "boxed" else -1,
            )
            for stage in resultStages
        ]

        foundHits = {}
        cleanClr = color["clean"]
        blocks = self.blocks
        markResults = {}

        for ((stripe, column), data) in blocks.items():
            if block is not None and block != (stripe, column):
                continue
            (leftB, topB, rightB, bottomB) = data["inner"]
            thisDemargined = demargined[topB:bottomB, leftB:rightB]

            for (band, markData) in searchMarks.items():
                bandData = data["bands"][band]
                uppers = bandData["uppers"]
                lowers = bandData["lowers"]

                for (markName, markInfo) in markData.items():
                    foundHits.setdefault(band, {})[markName] = 0
                    seq = markInfo["seq"]
                    mark = markInfo["gray"]
                    connectBorder = markInfo["connectBorder"]
                    accuracy = markInfo["accuracy"]
                    ratio = markInfo["connectRatio"]
                    (markH, markW) = mark.shape[:2]

                    nPts = 0
                    clusters = []
                    for (i, (upper, lower)) in enumerate(zip(uppers, lowers)):
                        if line is not None:
                            if i < line - 1:
                                continue
                            elif i > line - 1:
                                break
                        roi = thisDemargined[
                            upper : lower + 1,
                        ]
                        (roih, roiw) = roi.shape[:2]
                        if roih < markH or roiw < markW:
                            # search template exceeds roi image
                            continue
                        if line is not None:
                            showImage(roi)
                        result = cv2.matchTemplate(roi, mark, cv2.TM_CCOEFF_NORMED)
                        loc = np.where(result >= accuracy)
                        pts = list(zip(*loc))
                        if len(pts) > maxHits:
                            error(
                                f"mark '{band}:{markName}':"
                                f" too many hits: {len(pts)} > {maxHits}"
                            )
                            warning("Increase accuracy for this template")
                            continue
                        if not pts:
                            continue

                        nPts += len(pts)
                        clusters = cluster(pts, result)

                        for (pt, value) in clusters:
                            connDegree = connected(
                                markH, markW, connectBorder, threshold, roi, pt
                            )
                            pt = (pt[0] + upper + topB, pt[1] + leftB)
                            (top, bottom, left, right) = (
                                pt[0],
                                pt[0] + markH,
                                pt[1],
                                pt[1] + markW,
                            )
                            if connDegree > ratio:
                                if showKept and (not batch or boxed):
                                    im = stages["boxed"]
                                    addBox(
                                        C,
                                        im,
                                        top,
                                        bottom,
                                        left,
                                        right,
                                        True,
                                        band,
                                        seq,
                                        connDegree,
                                    )
                                    markResults.setdefault(band, {}).setdefault(
                                        (seq, markName), []
                                    ).append(
                                        (
                                            True,
                                            value,
                                            connDegree,
                                            connectBorder,
                                            stripe,
                                            column,
                                            top,
                                            bottom,
                                            left,
                                            right,
                                        )
                                    )
                            else:
                                if batch and not boxed:
                                    cv2.rectangle(
                                        stages["clean"],
                                        (left, top),
                                        (right, bottom),
                                        cleanClr,
                                        -1,
                                    )
                                else:
                                    for (stage, im, clr, brd) in tasks:
                                        isBoxed = stage == "boxed"
                                        if isBoxed:
                                            addBox(
                                                C,
                                                im,
                                                top,
                                                bottom,
                                                left,
                                                right,
                                                False,
                                                band,
                                                seq,
                                                connDegree,
                                            )
                                            markResults.setdefault(band, {}).setdefault(
                                                (seq, markName), []
                                            ).append(
                                                (
                                                    False,
                                                    value,
                                                    connDegree,
                                                    connectBorder,
                                                    stripe,
                                                    column,
                                                    top,
                                                    bottom,
                                                    left,
                                                    right,
                                                )
                                            )
                                        else:
                                            cv2.rectangle(
                                                im,
                                                (left, top),
                                                (right, bottom),
                                                clr,
                                                -1,
                                            )

        stages["markData"] = markResults
        for (band, bandMarks) in sorted(markResults.items()):
            for ((seq, mark), entries) in sorted(bandMarks.items()):
                indent(level=2)
                kept = sum(1 for e in entries if e[0])
                wiped = len(entries) - kept
                warning(
                    f"{seq:>2} - {band:<10}: {mark:<20}"
                    f" wiped {wiped:>4} x, kept {kept:>4} x",
                    tm=False,
                )
        indent(level=1)
        info("cleaning done")

    def _showCleanInfo(self):
        """Pretty-prints the result of the cleaning stage.
        """

        engine = self.engine
        tm = engine.tm
        info = tm.info
        indent = tm.indent
        stages = self.stages
        markData = stages.get("markData", {})
        total = 0

        total = 0
        for (band, markInfo) in sorted(markData.items()):
            indent(level=0)
            info(band, tm=False)
            for ((seq, mark), entries) in sorted(markInfo.items()):
                indent(level=1)
                wiped = sum(1 for e in entries if not e[0])
                total += wiped
                notWiped = len(entries) - wiped
                showImage(engine.marks[band][mark]["gray"])
                info(
                    f"{seq:>2}: {mark:<20} wiped {wiped:>4} x, kept {notWiped:>4} x",
                    tm=False,
                )
                info(
                    f"{'':24} kept  {notWiped:>4} x", tm=False,
                )
                for (
                    k,
                    value,
                    conn,
                    border,
                    stripe,
                    column,
                    top,
                    bottom,
                    left,
                    right,
                ) in sorted(entries):
                    indent(level=2)
                    wRep = "kept" if k else "wiped"
                    block = f"{stripe}{column}"
                    info(
                        f"{wRep:<5} [{block:>3}]"
                        f" tblr={top:>4} {bottom:>4} {left:>4} {right:>4},"
                        f" value={value:5.2f} conn={conn:5.3f} border={border:>2}",
                        tm=False,
                    )

    def _ocr(self):
        """Calls the OCR engine for a page.
        """

        stages = self.stages

        reader = OCR(self.engine, page=self)
        stages["ocrData"] = reader.read()
