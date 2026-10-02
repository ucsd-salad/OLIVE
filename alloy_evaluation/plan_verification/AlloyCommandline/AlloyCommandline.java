import edu.mit.csail.sdg.alloy4.A4Reporter;
import edu.mit.csail.sdg.alloy4.ConstList;
import edu.mit.csail.sdg.alloy4.ErrorWarning;
import edu.mit.csail.sdg.ast.Command;
import edu.mit.csail.sdg.ast.Module;
import edu.mit.csail.sdg.ast.Func;
import java.util.HashSet;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Set;
import edu.mit.csail.sdg.parser.CompUtil;
import edu.mit.csail.sdg.translator.A4Options;
import edu.mit.csail.sdg.translator.A4Solution;
import edu.mit.csail.sdg.translator.TranslateAlloyToKodkod;

/**
 * Usage: java AlloyCommandline <file.als> [rule ...]
 *
 * Parses the file; any type warning is printed as `WARNING ...` and ends the
 * run (see below). Otherwise runs EVERY command in the file, in order, and
 * prints for each one
 *
 *   COMMAND <label>: Instance found | No instance found
 *
 * For a command that finds an instance, the instance follows between
 * BEGIN INSTANCE / END INSTANCE, and then one line per rule named on the
 * command line:
 *
 *   RULE <name>: holds | VIOLATED
 *
 * evaluated in that instance. For a counterexample to a plan, the VIOLATED
 * lines say which protocol rules the counterexample breaks.
 */
public class AlloyCommandline {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) return;
        String filename = args[0];

        // 1. 解析模型. A comparison between disjoint types (`p.age = True`) is only
        // a warning in Alloy, yet it is constantly false and silently changes what
        // the plan says -- so, as in the roundtrip, a warning fails the file and no
        // command is run.
        final int[] warnings = {0};
        A4Reporter reporter = new A4Reporter() {
            @Override
            public void warning(ErrorWarning msg) {
                // an unused variable changes nothing the model says
                if (msg.toString().contains("This variable is unused")) return;
                warnings[0]++;
                System.out.println("WARNING " + msg.toString().trim().replace("\n", " | "));
            }
        };
        Module world = CompUtil.parseEverything_fromFile(reporter, null, filename);
        if (warnings[0] > 0) {
            System.out.println("Type warning: " + warnings[0] + " warning(s); no command was run.");
            return;
        }
        if (Arrays.asList(args).contains("--syntax-only")) {
            System.out.println("COMPILED: GeneratedPlan");
            return;
        }

        Func plan = null;
        Set<Func> forbidden = new HashSet<>();
        ArrayDeque<Func> pending = new ArrayDeque<>();
        for (Func function : world.getAllReachableUserDefinedFunc()) {
            String name = function.label.substring(function.label.lastIndexOf('/') + 1);
            if (name.equals("GeneratedPlan")) plan = function;
            if (name.equals("Protocol")) pending.add(function);
        }
        while (!pending.isEmpty()) {
            Func function = pending.removeFirst();
            // Shared integer primitives are arithmetic, not safety-specification helpers.
            if (function.label.startsWith("integer/")) continue;
            if (!forbidden.add(function)) continue;
            for (Func called : function.getBody().findAllFunctions()) pending.add(called);
        }
        if (plan != null) {
            // Calling the safety property makes verification circular. Use resolved
            // calls so a field such as lg.eyesOnWater is not confused with a predicate.
            for (Func called : plan.getBody().findAllFunctions()) {
                if (forbidden.contains(called)) {
                    System.out.println("INVALID_PLAN: Describe concrete constraints instead of calling "
                        + called.label + ", part of the safety specification.");
                    return;
                }
            }
        }

        // 2. 配置选项 (默认即为 SAT4J). Instances with an integer overflow are
        // excluded, the same rule as the roundtrip's `exec -n`: a wrapped-around
        // value would be a counterexample the protocol never meant.
        A4Options options = new A4Options();
        options.noOverflow = true;

        // 3. 依次执行所有命令
        ConstList<Command> commands = world.getAllCommands();
        if (commands.isEmpty()) {
            System.out.println("No commands found.");
            return;
        }

        for (Command command : commands) {
            A4Solution res = TranslateAlloyToKodkod.execute_command(
                A4Reporter.NOP,
                world.getAllReachableSigs(),
                command,
                options
            );

            // 4. 输出结果
            if (!res.satisfiable()) {
                System.out.println("COMMAND " + command.label + ": No instance found");
                continue;
            }
            System.out.println("COMMAND " + command.label + ": Instance found");
            System.out.println("BEGIN INSTANCE");
            for (String line : res.toString().split("\n")) {
                // the integer range and the empty built-ins say nothing about the plan
                if (line.startsWith("univ=") || line.startsWith("Int=")
                        || line.startsWith("seq/Int=") || line.startsWith("String=")
                        || line.startsWith("none=") || line.startsWith("---")
                        || line.trim().isEmpty()) {
                    continue;
                }
                System.out.println(line);
            }
            System.out.println("END INSTANCE");
            for (int i = 1; i < args.length; i++) {
                Object value = res.eval(CompUtil.parseOneExpression_fromString(world, args[i]));
                System.out.println("RULE " + args[i] + ": "
                    + (Boolean.TRUE.equals(value) ? "holds" : "VIOLATED"));
            }
        }
    }
}
