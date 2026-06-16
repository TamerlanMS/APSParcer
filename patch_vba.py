"""
patch_vba.py — Обновляет VBA-макросы в шаблоне .xlsm

Какие модули обновляются
─────────────────────────
  Лист2         — «WV 4.0»
                  Worksheet_Change: поиск в БД B:J + обновление всей строки
                  UpdateWVRow:      A=Бренд, B=Артикул, C=Наим., D=Ед., G очищается, E сохраняется
                  Worksheet_SelectionChange / Worksheet_Activate — без изменений

  вкл_выкл_макрос — Public EnableMyMacro + ToggleMacroEng (Ctrl+Q) + ToggleMacroRus (Ctrl+Й)

  UserForm1     — Форма выбора наименования (без изменений — патч пропускает, если уже есть)

Как использовать
─────────────────
  python patch_vba.py                          # патчит assets/WV_template.xlsm
  python patch_vba.py path\\to\\template.xlsm  # патчит указанный файл

Требования
───────────
  • Windows + Microsoft Excel установлен
  • pip install pywin32
  • В Excel включено «Доверять доступ к объектной модели проекта VBA»:
      Файл → Параметры → Центр управления безопасностью →
      Параметры центра → Параметры макросов →
      ✅ Доверять доступ к объектной модели проекта VBA

Архитектура обновления макросов в приложении
─────────────────────────────────────────────
  1. Запустить patch_vba.py на шаблоне (один раз при каждом изменении VBA).
  2. Загрузить обновлённый шаблон на сервер через вкладку «Шаблон» в приложении.
  3. Все последующие сохранения КП автоматически используют серверный шаблон
     (excel_generator.py → download_excel_template → openpyxl keep_vba=True).
     Макросы переносятся как есть — Python их не трогает.
"""

import os
import sys


# ── Код модулей ──────────────────────────────────────────────────────────────

# Лист2 (WV 4.0) — полный код
ЛИСТ2_CODE = """\
Option Explicit

' =============================================================================
' Лист2 = «WV 4.0»
'
' Worksheet_Change:
'   Срабатывает при вводе/изменении ячейки в столбце B (Артикул).
'   1. Ищет значение в БД!B:J.
'   2. Точное совпадение  → сразу обновляет всю строку WV 4.0.
'   3. Несколько частичных совпадений → UserForm1 для выбора.
'   4. После выбора → UpdateWVRow.
'
' UpdateWVRow:
'   A = Бренд (БД!J),  B = Артикул,  C = Наименование (БД!C)
'   D = Ед.изм. (БД!D),  E = Количество (НЕ трогаем),  G = очищается
'
' Вкл/Выкл: Ctrl+Q (англ.) / Ctrl+Й (рус.)
' =============================================================================

Private Sub Worksheet_Change(ByVal Target As Range)
    If Not EnableMyMacro Then Exit Sub

    Dim intersectRange As Range
    Set intersectRange = Intersect(Target, Me.Columns(2))
    If intersectRange Is Nothing Then Exit Sub

    On Error GoTo CleanUp
    Application.EnableEvents = False
    Application.ScreenUpdating = False

    Dim wsData As Worksheet
    Set wsData = ThisWorkbook.Sheets("БД")

    Dim lastRow As Long
    lastRow = wsData.Cells(wsData.Rows.Count, "B").End(xlUp).Row
    If lastRow < 2 Then GoTo CleanUp

    ' Читаем БД B:J в массив — B=1, C=2, D=3, ..., J=9
    Dim arrData As Variant
    arrData = wsData.Range("B1:J" & lastRow).Value

    Dim tCell As Range
    For Each tCell In intersectRange
        If Not IsEmpty(tCell.Value) Then
            Dim strSearch As String
            strSearch = LCase$(Trim$(CStr(tCell.Value)))
            If Len(strSearch) = 0 Then GoTo NextCell

            Dim matches As Collection
            Dim matchIndices As Collection
            Set matches = New Collection
            Set matchIndices = New Collection

            Dim exactMatchIdx As Long
            exactMatchIdx = 0

            Dim i As Long
            For i = 1 To UBound(arrData, 1)
                Dim ValB As String, valC As String
                ValB = CStr(arrData(i, 1))
                valC = CStr(arrData(i, 2))

                If LCase$(ValB) = strSearch Or LCase$(valC) = strSearch Then
                    exactMatchIdx = i
                    Exit For
                End If

                If InStr(1, ValB, strSearch, vbTextCompare) > 0 Or _
                   InStr(1, valC, strSearch, vbTextCompare) > 0 Then
                    matches.Add arrData(i, 1) & " - " & valC
                    matchIndices.Add i
                End If
            Next i

            If exactMatchIdx > 0 Then
                Call UpdateWVRow(tCell, _
                    CStr(arrData(exactMatchIdx, 1)), _
                    CStr(arrData(exactMatchIdx, 2)), _
                    CStr(arrData(exactMatchIdx, 3)), _
                    CStr(arrData(exactMatchIdx, 9)))

            ElseIf matches.Count > 0 Then
                Dim frm As UserForm1
                Set frm = New UserForm1
                frm.lstMatches.Clear

                Dim matchItem As Variant
                For Each matchItem In matches
                    frm.lstMatches.AddItem matchItem
                Next matchItem

                Dim result As String
                result = frm.GetSelectedValue
                Unload frm

                If result <> "" Then
                    Dim selectedIdx As Long
                    selectedIdx = 0
                    Dim j As Long
                    For j = 1 To matches.Count
                        If matches(j) = result Then
                            selectedIdx = matchIndices(j)
                            Exit For
                        End If
                    Next j

                    If selectedIdx > 0 Then
                        Call UpdateWVRow(tCell, _
                            CStr(arrData(selectedIdx, 1)), _
                            CStr(arrData(selectedIdx, 2)), _
                            CStr(arrData(selectedIdx, 3)), _
                            CStr(arrData(selectedIdx, 9)))
                    Else
                        tCell.Value = Split(result, " - ")(0)
                    End If
                End If
            End If

NextCell:
        End If
    Next tCell

CleanUp:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
End Sub


Private Sub UpdateWVRow(tCell As Range, article As String, name As String, unit As String, brand As String)
    Dim r As Long
    r = tCell.Row
    Me.Cells(r, 1).Value = brand    ' A — Бренд
    tCell.Value           = article  ' B — Артикул
    Me.Cells(r, 3).Value = name     ' C — Наименование
    Me.Cells(r, 4).Value = unit     ' D — Единица измерения
    ' E (Количество) — НЕ ТРОГАЕМ
    Me.Cells(r, 7).Value = ""       ' G — сбрасываем константу цены
End Sub


Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Target.Cells.CountLarge > 1 Then Exit Sub
    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub
    Target.Calculate
End Sub


Private Sub Worksheet_Activate()
    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub
    On Error Resume Next
    Application.EnableEvents = False
    Application.ScreenUpdating = False
    Me.Calculate
    Application.CalculateFull
    Application.ScreenUpdating = True
    Application.EnableEvents = True
    On Error GoTo 0
End Sub
"""


# вкл_выкл_макрос.bas — полный код
ВКЛ_ВЫКЛ_CODE = """\
Option Explicit

' =============================================================================
' вкл_выкл_макрос
'
' Управляет флагом EnableMyMacro — переключателем макроса поиска
' артикулов на листе WV 4.0.
'
' Горячие клавиши:
'   Ctrl + Q  (английская раскладка)
'   Ctrl + Й  (русская раскладка)
'
' По умолчанию при открытии книги макрос ВЫКЛЮЧЕН.
' =============================================================================

Public EnableMyMacro As Boolean

Sub EnableMacro()
    EnableMyMacro = True
    MsgBox "Макрос включён", vbInformation, "Статус"
End Sub

Sub DisableMacro()
    EnableMyMacro = False
    MsgBox "Макрос отключён", vbInformation, "Статус"
End Sub

Sub ToggleMacroEng()
Attribute ToggleMacroEng.VB_ProcData.VB_Invoke_Func = "q\\n14"
    If EnableMyMacro Then
        Call DisableMacro
    Else
        Call EnableMacro
    End If
End Sub

Sub ToggleMacroRus()
Attribute ToggleMacroRus.VB_ProcData.VB_Invoke_Func = "й\\n14"
    If EnableMyMacro Then
        Call DisableMacro
    Else
        Call EnableMacro
    End If
End Sub
"""


# ── Основная функция патча ────────────────────────────────────────────────────

def patch_xlsm(xlsm_path: str) -> None:
    """Открывает xlsm через Excel COM, обновляет VBA-модули, сохраняет."""
    import win32com.client as win32

    abs_path = os.path.abspath(xlsm_path)
    print(f"\nПатчим: {abs_path}")

    excel = win32.Dispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False

    wb = excel.Workbooks.Open(abs_path, ReadOnly=False, UpdateLinks=False)

    try:
        vba_project = wb.VBProject
    except AttributeError:
        wb.Close(SaveChanges=False)
        excel.Quit()
        _print_trust_instructions()
        sys.exit(1)

    # Индекс компонентов по имени
    components = {c.Name: c for c in vba_project.VBComponents}
    print(f"  Компоненты VBA: {sorted(components.keys())}")

    # ── Патч Лист2 ──────────────────────────────────────────────────────────
    _patch_module(components, "Лист2", ЛИСТ2_CODE)

    # ── Патч вкл_выкл_макрос ────────────────────────────────────────────────
    _patch_module(components, "вкл_выкл_макрос", ВКЛ_ВЫКЛ_CODE)

    # ── Привязка горячих клавиш через Application.MacroOptions ──────────────
    # (дополнительная гарантия помимо Attribute в коде)
    try:
        excel.MacroOptions(Macro=f"'{os.path.basename(abs_path)}'!ToggleMacroEng",
                           Description="Вкл/Выкл макрос поиска (англ.)",
                           ShortcutKey="q")
        excel.MacroOptions(Macro=f"'{os.path.basename(abs_path)}'!ToggleMacroRus",
                           Description="Вкл/Выкл макрос поиска (рус.)",
                           ShortcutKey="й")
        print("  Горячие клавиши Ctrl+Q / Ctrl+Й — назначены")
    except Exception as e:
        print(f"  ⚠ Горячие клавиши: {e} (назначьте вручную через Сервис → Макросы → Параметры)")

    # ── Сохранение ──────────────────────────────────────────────────────────
    wb.Save()
    wb.Close(SaveChanges=False)
    excel.Quit()

    print(f"\n✅ Готово! Загрузите файл на сервер через вкладку «Шаблон» в приложении.")
    print(f"   Файл: {abs_path}")


def _patch_module(components: dict, module_name: str, new_code: str) -> None:
    """Заменяет код VBA-модуля."""
    if module_name not in components:
        print(f"  ⚠ Компонент {module_name!r} не найден, пропускаем")
        return

    comp = components[module_name]
    cm = comp.CodeModule
    old_lines = cm.CountOfLines
    if old_lines > 0:
        cm.DeleteLines(1, old_lines)
    cm.AddFromString(new_code)
    print(f"  ✓ {module_name}: {old_lines} → {cm.CountOfLines} строк")


def _print_trust_instructions() -> None:
    print()
    print("ОШИБКА: нет доступа к VBProject.")
    print("Включите «Доверять доступ к объектной модели проекта VBA» в Excel:")
    print()
    print("  Файл → Параметры → Центр управления безопасностью →")
    print("  Параметры центра → Параметры макросов →")
    print("  ✅ Доверять доступ к объектной модели проекта VBA")
    print()
    print("После этого снова запустите patch_vba.py.")


# ── Точка входа ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        xlsm_path = sys.argv[1]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Сначала ищем в uploads (если пользователь скачал шаблон с сервера)
        candidates = [
            os.path.join(script_dir, "client", "assets", "WV_template.xlsm"),
            os.path.join(script_dir, "WV_template.xlsm"),
        ]
        xlsm_path = next((p for p in candidates if os.path.exists(p)), None)
        if not xlsm_path:
            print("Укажите путь к файлу:")
            print("  python patch_vba.py path\\to\\WV_template.xlsm")
            sys.exit(1)

    if not os.path.exists(xlsm_path):
        print(f"Файл не найден: {xlsm_path}")
        sys.exit(1)

    patch_xlsm(xlsm_path)


if __name__ == "__main__":
    main()
